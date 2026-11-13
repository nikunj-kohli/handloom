"""Signed handover export: a snapshot payload, Markdown and PDF.

The export is built from a stored snapshot, so a signed handover never changes when
someone later edits a claim.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional, Sequence

from .. import config
from ..security import fingerprint
from . import taxonomy

CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def build_snapshot(
    session: Dict[str, Any],
    claims: Sequence[Dict[str, Any]],
    gaps: Sequence[Dict[str, Any]],
    decisions: Sequence[Dict[str, Any]],
    evidence_index: Dict[str, Dict[str, Any]],
    reviewer: str,
    signed_at: str,
) -> Dict[str, Any]:
    approved = [claim for claim in claims if claim["status"] in ("approved", "edited")]
    rejected = [claim for claim in claims if claim["status"] == "rejected"]
    pending = [claim for claim in claims if claim["status"] in ("pending", "needs_confirmation")]
    dropped = [claim for claim in claims if claim["status"] == "dropped"]

    sections: List[Dict[str, Any]] = []
    for section in config.SECTIONS:
        section_claims = [claim for claim in approved if claim["section"] == section["key"]]
        if not section_claims:
            continue
        sections.append(
            {
                "key": section["key"],
                "label": section["label"],
                "claims": [_claim_entry(claim, evidence_index) for claim in section_claims],
            }
        )

    audit = [
        {
            "claim_id": row["claim_id"],
            "action": row["action"],
            "at": row["at"],
            "reviewer": row["reviewer"],
            "note": row.get("note"),
        }
        for row in decisions
    ]

    payload: Dict[str, Any] = {
        "project": session.get("project_name") or "Handover",
        "leaver": session.get("leaver_name") or "",
        "repo": session.get("repo_full_name"),
        "window": {"start": session.get("window_start"), "end": session.get("window_end")},
        "mode": session.get("mode"),
        "session_id": session.get("id"),
        "generated_at": session.get("updated_at"),
        "signed_at": signed_at,
        "reviewer": reviewer,
        "sections": sections,
        "gaps": [
            {
                "area": gap["area"],
                "label": gap.get("area_label") or taxonomy.label(gap["area"]),
                "reason": gap["reason"],
                "evidence_count": gap["evidence_count"],
                "evidence": [_evidence_entry(evidence_index[i]) for i in gap["evidence_ids"] if i in evidence_index],
            }
            for gap in gaps
        ],
        "audit": audit,
        "counts": {
            "approved": len([claim for claim in approved if claim["status"] == "approved"]),
            "edited": len([claim for claim in approved if claim["status"] == "edited"]),
            "rejected": len(rejected),
            "pending": len(pending),
            "dropped": len(dropped),
            "sections": len(sections),
            "gaps": len(gaps),
        },
        "omitted": [
            {
                "id": claim["id"],
                "section": claim["section"],
                "text": claim["text"],
                "status": claim["status"],
                "reason": claim.get("verification_note")
                if claim["status"] == "dropped"
                else "Not approved by the reviewer.",
            }
            for claim in list(rejected) + list(dropped)
        ][:20],
        "sample_data": session.get("mode") == "sample",
    }
    payload["fingerprint"] = fingerprint(_canonical(payload))
    return payload


def _canonical(payload: Dict[str, Any]) -> str:
    material = {
        "leaver": payload.get("leaver"),
        "window": payload.get("window"),
        "sections": [
            {"key": section["key"], "claims": [claim["text"] for claim in section["claims"]]}
            for section in payload.get("sections", [])
        ],
        "gaps": [gap["area"] for gap in payload.get("gaps", [])],
    }
    return json.dumps(material, sort_keys=True, ensure_ascii=False)


def _evidence_entry(item: Dict[str, Any]) -> Dict[str, Any]:
    body = " ".join((item.get("body") or "").split())
    return {
        "id": item["id"],
        "source_type": item.get("source_type"),
        "source_label": item.get("source_label"),
        "external_id": item.get("external_id"),
        "title": item.get("title"),
        "author": item.get("author"),
        "occurred_at": item.get("occurred_at"),
        "url": item.get("url"),
        "areas": item.get("areas") or [],
        "excerpt": (body[:400] + "…") if len(body) > 400 else body,
    }


def _claim_entry(claim: Dict[str, Any], evidence_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "id": claim["id"],
        "text": claim.get("final_text") or claim["text"],
        "original_text": claim["text"] if claim.get("final_text") else None,
        "confidence": claim["confidence"],
        "claim_type": claim["claim_type"],
        "origin": claim["origin"],
        "verification": claim.get("verification"),
        "verification_note": claim.get("verification_note"),
        "reviewer_note": claim.get("note"),
        "status": claim["status"],
        "evidence": [_evidence_entry(evidence_index[i]) for i in claim["evidence_ids"] if i in evidence_index],
    }


# --------------------------------------------------------------------------- markdown
def render_markdown(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Handover: %s" % (payload.get("project") or "Project"))
    lines.append("")
    if payload.get("sample_data"):
        lines.append(
            "> **Sample data.** This handover was produced from a synthetic demo project. "
            "The people, commits and messages are invented for the demo."
        )
        lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append("| Leaving | %s |" % (payload.get("leaver") or "—"))
    lines.append(
        "| Period | %s to %s |"
        % (_value(payload["window"].get("start")), _value(payload["window"].get("end")))
    )
    if payload.get("repo"):
        lines.append("| Repository | %s |" % payload["repo"])
    lines.append("| Reviewed and signed by | %s |" % payload.get("reviewer"))
    lines.append("| Signed at | %s |" % payload.get("signed_at"))
    lines.append("| Content fingerprint | `%s` |" % payload.get("fingerprint"))
    lines.append("")
    counts = payload.get("counts", {})
    lines.append(
        "**%d approved · %d edited · %d rejected · %d still pending · %d dropped by the citation verifier**"
        % (
            counts.get("approved", 0),
            counts.get("edited", 0),
            counts.get("rejected", 0),
            counts.get("pending", 0),
            counts.get("dropped", 0),
        )
    )
    lines.append("")

    for section in payload.get("sections", []):
        lines.append("## %s" % section["label"])
        lines.append("")
        for claim in section["claims"]:
            marker = "edited" if claim.get("original_text") else claim.get("status", "approved")
            lines.append("- %s" % claim["text"])
            lines.append(
                "  <sub>%s · %s · %s · %s</sub>"
                % (claim["confidence"].upper(), claim["origin"], claim["claim_type"], marker)
            )
            if claim.get("reviewer_note"):
                lines.append("  <sub>Reviewer note: %s</sub>" % claim["reviewer_note"])
            for item in claim.get("evidence", []):
                lines.append("  - Evidence: %s" % _evidence_line(item))
            lines.append("")

    gaps = payload.get("gaps", [])
    lines.append("## Coverage check")
    lines.append("")
    if gaps:
        lines.append(
            "These areas were touched by the leaver but are **not** represented in any approved claim. "
            "They are listed so the successor knows what to ask about."
        )
        lines.append("")
        for gap in gaps:
            lines.append("- **%s** — %s" % (gap["label"], gap["reason"]))
            for item in gap.get("evidence", [])[:3]:
                lines.append("  - %s" % _evidence_line(item))
        lines.append("")
    else:
        lines.append("Every area with recorded activity is represented by at least one approved claim.")
        lines.append("")

    audit = payload.get("audit", [])
    lines.append("## Approval log")
    lines.append("")
    if audit:
        lines.append("| When | Reviewer | Claim | Decision | Note |")
        lines.append("|---|---|---|---|---|")
        for row in audit:
            lines.append(
                "| %s | %s | %s | %s | %s |"
                % (row["at"], row["reviewer"], row["claim_id"], row["action"], row.get("note") or "")
            )
    else:
        lines.append("No individual decisions were logged.")
    lines.append("")

    omitted = payload.get("omitted", [])
    if omitted:
        lines.append("## Omitted from this handover")
        lines.append("")
        for row in omitted:
            lines.append(
                "- `%s` (%s, %s) — %s" % (row["id"], row["section"], row["status"], row["text"][:220])
            )
        lines.append("")

    lines.append("---")
    lines.append(
        "Generated by Handover Lens. Only approved or edited claims appear above; every claim is traceable "
        "to a cited record. Fingerprint `%s` covers the claim text, period and coverage list."
        % payload.get("fingerprint")
    )
    return "\n".join(lines)


def _evidence_line(item: Dict[str, Any]) -> str:
    stamp = (item.get("occurred_at") or "")[:10]
    link = item.get("url")
    label = "%s · %s · %s" % (
        item.get("source_type"),
        item.get("author") or "unattributed",
        stamp or "no date",
    )
    title = item.get("title") or item.get("external_id") or "record"
    if link:
        return "[%s](%s) — %s (`%s`)" % (title, link, label, item.get("id"))
    return "%s — %s (`%s`)" % (title, label, item.get("id"))


def _value(value: Optional[str]) -> str:
    return value or "—"


# --------------------------------------------------------------------------- pdf
def render_pdf(payload: Dict[str, Any]) -> bytes:
    """reportlab is imported lazily so Markdown export never depends on it."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Handover — %s" % (payload.get("project") or ""),
        author="Handover Lens",
    )

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12.5,
        spaceAfter=3,
        wordWrap="CJK",
        textColor=colors.HexColor("#1f2328"),
    )
    small = ParagraphStyle(
        "Small", parent=body, fontSize=7.5, leading=10, textColor=colors.HexColor("#5b6570")
    )
    h1 = ParagraphStyle(
        "H1",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=21,
        textColor=colors.HexColor("#111417"),
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor("#111417"),
        spaceBefore=12,
        spaceAfter=5,
    )
    meta = ParagraphStyle("Meta", parent=body, fontSize=8.5, textColor=colors.HexColor("#40474f"))

    story: List[Any] = []
    story.append(Paragraph("Handover: %s" % escape(str(payload.get("project") or "Project")), h1))
    if payload.get("sample_data"):
        story.append(
            Paragraph(
                "<b>Sample data.</b> Produced from a synthetic demo project; the people, commits and "
                "messages are invented for the demo.",
                small,
            )
        )
        story.append(Spacer(1, 4))

    counts = payload.get("counts", {})
    story.append(
        Paragraph(
            "Leaving <b>%s</b> · period %s to %s"
            % (
                escape(str(payload.get("leaver") or "—")),
                _value(payload["window"].get("start")),
                _value(payload["window"].get("end")),
            ),
            meta,
        )
    )
    if payload.get("repo"):
        story.append(Paragraph("Repository: %s" % escape(str(payload["repo"])), meta))
    story.append(
        Paragraph(
            "Signed by <b>%s</b> at %s · fingerprint <b>%s</b>"
            % (
                escape(str(payload.get("reviewer") or "")),
                escape(str(payload.get("signed_at") or "")),
                payload.get("fingerprint"),
            ),
            meta,
        )
    )
    story.append(
        Paragraph(
            "%d approved · %d edited · %d rejected · %d pending · %d dropped by the citation verifier"
            % (
                counts.get("approved", 0),
                counts.get("edited", 0),
                counts.get("rejected", 0),
                counts.get("pending", 0),
                counts.get("dropped", 0),
            ),
            meta,
        )
    )

    for section in payload.get("sections", []):
        story.append(Paragraph(escape(section["label"]), h2))
        for claim in section["claims"]:
            tag = "%s · %s · %s" % (claim["confidence"].upper(), claim["origin"], claim["status"])
            story.append(Paragraph("• %s" % escape(claim["text"]), body))
            story.append(Paragraph(escape(tag), small))
            if claim.get("reviewer_note"):
                story.append(Paragraph("Reviewer note: %s" % escape(claim["reviewer_note"]), small))
            for item in claim.get("evidence", []):
                story.append(Paragraph("↳ %s" % escape(_evidence_line_plain(item)), small))
            story.append(Spacer(1, 3))

    gaps = payload.get("gaps", [])
    story.append(Paragraph("Coverage check", h2))
    if gaps:
        story.append(
            Paragraph(
                "Areas the leaver touched that no approved claim represents. The successor should ask about these.",
                body,
            )
        )
        for gap in gaps:
            story.append(Paragraph("• <b>%s</b> — %s" % (escape(gap["label"]), escape(gap["reason"])), body))
    else:
        story.append(
            Paragraph("Every area with recorded activity is represented by an approved claim.", body)
        )

    audit = payload.get("audit", [])
    story.append(Paragraph("Approval log", h2))
    if audit:
        for row in audit:
            story.append(
                Paragraph(
                    "%s — %s — %s — %s%s"
                    % (
                        escape(str(row["at"])),
                        escape(str(row["reviewer"])),
                        escape(str(row["claim_id"])),
                        escape(str(row["action"])),
                        (" — " + escape(str(row["note"]))) if row.get("note") else "",
                    ),
                    small,
                )
            )
    else:
        story.append(Paragraph("No individual decisions were logged.", small))

    omitted = payload.get("omitted", [])
    if omitted:
        story.append(Paragraph("Omitted from this handover", h2))
        for row in omitted:
            story.append(
                Paragraph(
                    "%s (%s, %s) — %s"
                    % (row["id"], row["section"], row["status"], escape(row["text"][:200])),
                    small,
                )
            )

    def decorate(canvas: Any, _doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#7b858f"))
        canvas.drawString(18 * mm, 10 * mm, "Handover Lens · fingerprint %s" % payload.get("fingerprint"))
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, "Page %d" % canvas.getPageNumber())
        canvas.restoreState()

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def _evidence_line_plain(item: Dict[str, Any]) -> str:
    stamp = (item.get("occurred_at") or "")[:10]
    base = "%s · %s · %s · %s" % (
        item.get("source_type"),
        item.get("author") or "unattributed",
        stamp or "no date",
        item.get("id"),
    )
    if item.get("url"):
        base += " · %s" % item["url"]
    return base


# --------------------------------------------------------------------------- traceability
TRACE_COLUMNS = [
    "claim_id",
    "section",
    "section_label",
    "status",
    "confidence",
    "origin",
    "verification",
    "claim_text",
    "evidence_id",
    "source_type",
    "source_label",
    "author",
    "occurred_at",
    "url",
    "evidence_title",
    "evidence_excerpt",
]

# Spreadsheet software evaluates cells that begin with these characters.
_ACTIVE_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    text = " ".join(str(value if value is not None else "").split())
    if text[:1] in _ACTIVE_PREFIXES:
        text = "'" + text
    return text


def _trace_row(claim: Dict[str, Any], item: Optional[Dict[str, Any]]) -> Dict[str, str]:
    return {
        "claim_id": _cell(claim.get("id")),
        "section": _cell(claim.get("section")),
        "section_label": _cell(config.SECTION_LABELS.get(claim.get("section") or "", claim.get("section"))),
        "status": _cell(claim.get("status")),
        "confidence": _cell(claim.get("confidence")),
        "origin": _cell(claim.get("origin")),
        "verification": _cell(claim.get("verification")),
        "claim_text": _cell(claim.get("final_text") or claim.get("text")),
        "evidence_id": _cell(item.get("id") if item else ""),
        "source_type": _cell(item.get("source_type") if item else ""),
        "source_label": _cell(item.get("source_label") if item else ""),
        "author": _cell(item.get("author") if item else ""),
        "occurred_at": _cell(item.get("occurred_at") if item else ""),
        "url": _cell(item.get("url") if item else ""),
        "evidence_title": _cell(item.get("title") if item else ""),
        "evidence_excerpt": _cell((item.get("body") or "")[:240] if item else "(no evidence cited)"),
    }


def traceability_rows(
    claims: Sequence[Dict[str, Any]], evidence_index: Dict[str, Dict[str, Any]]
) -> List[Dict[str, str]]:
    """One row per claim/evidence pair, so a reviewer can filter the audit in a spreadsheet."""
    rows: List[Dict[str, str]] = []
    for claim in claims:
        cited = [evidence_index[i] for i in claim.get("evidence_ids") or [] if i in evidence_index]
        if not cited:
            rows.append(_trace_row(claim, None))
            continue
        for item in cited:
            rows.append(_trace_row(claim, item))
    return rows


def traceability_rows_from_payload(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """Same matrix, rebuilt from a frozen snapshot (approved claims plus omitted ones)."""
    rows: List[Dict[str, str]] = []
    for section in payload.get("sections", []):
        for claim in section["claims"]:
            entry = dict(claim, section=section["key"], id=claim.get("id"))
            evidence = claim.get("evidence") or []
            if not evidence:
                rows.append(_trace_row(entry, None))
                continue
            for item in evidence:
                rows.append(_trace_row(entry, item))
    for omitted in payload.get("omitted", []):
        rows.append(_trace_row(omitted, None))
    return rows


def render_traceability_csv(rows: Sequence[Dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=TRACE_COLUMNS, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()
