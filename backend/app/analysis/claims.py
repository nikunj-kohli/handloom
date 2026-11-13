"""Claim drafting: rule claims, then cited narrative claims, then verification.

Two drafting paths, both first-class:
* model path   — the configured provider drafts decisions/gotchas/first week, constrained to
  evidence ids, then every claim is citation-verified.
* offline path — a deterministic extractor quotes the records that carry rationale. It runs
  with no key, which is what keeps the demo alive when a quota or a network fails.

A claim never leaves this module without at least one real evidence id.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import config, llm
from . import rules, taxonomy, verify

DECISION_CUES = (
    "decided",
    "we chose",
    "chose ",
    "tradeoff",
    "trade-off",
    "because",
    "instead of",
    "sign off",
    "signed off on",
    "signed off",
    "deliberate",
    "is the gate",
    "not to enable",
    "blocked on",
    "open item",
    "only allows",
)

GOTCHA_CUES = (
    "don't touch",
    "do not",
    "careful",
    "known",
    "manual",
    "stopgap",
    "out of date",
    "edge case",
    "flaky",
    "doesn't fire",
    "does not fire",
    "lag",
    "unacceptable",
    "not fixed",
    "no audit trail",
    "requires a migration",
    "without talking",
    "without a load test",
    "under 1 unit",
    "hard-coded",
)

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
QUOTE_CHARS = 240


def _cue_pattern(cues: Sequence[str]):
    """Word-boundary cue matching: substring checks made 'flag' match 'lag'."""
    return re.compile(r"\b(?:%s)\b" % "|".join(re.escape(cue) for cue in cues), re.IGNORECASE)


DECISION_CUE_RE = _cue_pattern(DECISION_CUES)
GOTCHA_CUE_RE = _cue_pattern(GOTCHA_CUES)

NARRATIVE_SECTIONS = ("decisions", "gotchas", "first_week")


def build_claims(
    evidence: Sequence[Dict[str, Any]],
    leaver_name: str,
    leaver_email: str,
    window_start: Optional[str],
    window_end: Optional[str],
    project_name: str,
    use_llm: bool,
) -> Dict[str, Any]:
    index = {item["id"]: item for item in evidence}
    stats = rules.snapshot_stats(evidence, leaver_name, leaver_email)
    ownership_rows = rules.ownership(evidence, leaver_name, leaver_email)
    open_rows = rules.open_work(evidence, leaver_name, leaver_email)
    people_rows = rules.people(
        evidence, leaver_name, leaver_email, focus_areas=[row["area"] for row in ownership_rows[:4]]
    )

    claims: List[Dict[str, Any]] = []
    claims.extend(_snapshot_claims(stats, evidence, leaver_name, window_start, window_end))
    claims.extend(_ownership_claims(ownership_rows, leaver_name))
    claims.extend(_open_work_claims(open_rows, leaver_name))
    claims.extend(_people_claims(people_rows, leaver_name))

    narrative_note = ""
    model_claims: List[Dict[str, Any]] = []

    if use_llm:
        model_claims, narrative_note = _draft_with_model(
            evidence, leaver_name, window_start, window_end, stats, open_rows, people_rows
        )

    used_sentences: set = set()
    decisions = [claim for claim in model_claims if claim["section"] == "decisions"]
    gotchas = [claim for claim in model_claims if claim["section"] == "gotchas"]
    first_week = [claim for claim in model_claims if claim["section"] == "first_week"]

    if not decisions:
        decisions, used_sentences = _offline_narrative(evidence, "decisions", used_sentences)
    if not gotchas:
        gotchas, used_sentences = _offline_narrative(evidence, "gotchas", used_sentences)
    if not first_week:
        first_week = _offline_first_week(evidence, ownership_rows, open_rows, people_rows, leaver_name)

    claims.extend(decisions + gotchas + first_week)
    claims = _dedupe(claims)

    claims, dropped = verify.validate_ids(claims, set(index))
    claims = verify.heuristic_pass(claims, index)

    verification_note = "Every claim was checked against the cited text with the deterministic overlap check."
    model_only = [claim for claim in claims if claim.get("origin") == "model"]
    if model_only and use_llm:
        kept_model, dropped_model, note = verify.llm_pass(model_only, index)
        keep_ids = {id(claim) for claim in kept_model}
        claims = [claim for claim in claims if claim.get("origin") != "model" or id(claim) in keep_ids]
        dropped.extend(dropped_model)
        verification_note = note

    for claim in claims:
        claim["confidence"] = verify.confidence_for(claim)
        claim["status"] = "pending"
        claim["final_text"] = None
        claim["note"] = None

    section_order = {key: position for position, key in enumerate(config.SECTION_KEYS)}
    claims.sort(key=lambda claim: section_order.get(claim["section"], 99))

    ordered: List[Dict[str, Any]] = []
    counter = 1
    for claim in claims:
        claim["id"] = "CL-%04d" % counter
        counter += 1
        ordered.append(claim)

    for dropped_claim in dropped:
        dropped_claim["id"] = "CL-%04d" % counter
        counter += 1
        dropped_claim["status"] = "dropped"
        dropped_claim["confidence"] = "low"
        dropped_claim["final_text"] = None
        dropped_claim["verification_note"] = dropped_claim.get("drop_reason") or "Failed citation verification."
        ordered.append(dropped_claim)

    gaps = rules.coverage_gaps(evidence, ordered, leaver_name, leaver_email)

    by_section: Dict[str, int] = {}
    for claim in ordered:
        if claim["status"] == "dropped":
            continue
        by_section[claim["section"]] = by_section.get(claim["section"], 0) + 1

    return {
        "claims": ordered,
        "gaps": gaps,
        "dropped": len(dropped),
        "llm_used": bool(model_claims),
        "verification_note": " ".join(part for part in (narrative_note, verification_note) if part),
        "sections": by_section,
        "supporting": {
            "ownership": ownership_rows,
            "open_work": open_rows,
            "people": people_rows,
            "stats": stats,
        },
    }


# --------------------------------------------------------------------------- rule claims
def _claim(
    section: str,
    text: str,
    evidence_ids: Sequence[str],
    origin: str = "rules",
    claim_type: str = "rule",
    verification: str = "rules",
    note: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "section": section,
        "text": _trim(text),
        "evidence_ids": list(dict.fromkeys(evidence_ids))[:4],
        "origin": origin,
        "claim_type": claim_type,
        "verification": verification,
        "verification_note": note,
    }


def _trim(text: str, limit: int = 620) -> str:
    flattened = " ".join((text or "").split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 1].rstrip() + "…"


def _snapshot_claims(
    stats: Dict[str, Any],
    evidence: Sequence[Dict[str, Any]],
    leaver_name: str,
    window_start: Optional[str],
    window_end: Optional[str],
) -> List[Dict[str, Any]]:
    name = leaver_name or "The leaving engineer"
    period = "%s to %s" % (
        (window_start or stats.get("first_seen") or "?")[:10],
        (window_end or stats.get("last_seen") or "?")[:10],
    )
    claims: List[Dict[str, Any]] = []

    if not stats["leaver_records"]:
        fallback_ids = [item["id"] for item in evidence[:2]]
        if fallback_ids:
            claims.append(
                _claim(
                    "snapshot",
                    "No record in this window names %s as an author or owner. Check the spelling of the name, "
                    "or widen the date window — ownership and open work below will be thin." % name,
                    fallback_ids,
                )
            )
        return claims

    activity = []
    if stats["commits"]:
        activity.append("%d commits" % stats["commits"])
    if stats["pull_requests"]:
        activity.append("%d pull requests" % stats["pull_requests"])
    if stats["reviews"]:
        activity.append("%d reviews" % stats["reviews"])
    if stats["tasks"]:
        activity.append("%d tasks" % stats["tasks"])
    if stats["chats"]:
        activity.append("%d chat messages" % stats["chats"])

    ids = [item["id"] for item in evidence if rules.is_leaver(item, leaver_name)][:3]
    claims.append(
        _claim(
            "snapshot",
            "%s left %s of recorded activity between %s: %s."
            % (name, ", ".join(activity) if activity else "no commits", period, _area_phrase(stats["areas"])),
            ids or [item["id"] for item in evidence[:2]],
        )
    )

    if stats["areas"]:
        top = stats["areas"][:3]
        covered = sum(stats["area_counts"].get(area, 0) for area in top)
        total = sum(stats["area_counts"].values()) or 1
        claims.append(
            _claim(
                "snapshot",
                "Work concentrated in %s — %d of %d area-tagged records (%.0f%%)."
                % (_area_phrase(top), covered, total, 100.0 * covered / total),
                ids,
            )
        )
    return claims


def _area_phrase(areas: Sequence[str]) -> str:
    labels = [taxonomy.label(area) for area in areas if area]
    if not labels:
        return "no clear area"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _content_areas(areas: Sequence[str]) -> str:
    """Describe the subject matter of a document, not the fact that it is a document."""
    filtered = [area for area in areas if area not in ("docs", "unclassified")]
    return _area_phrase(filtered or list(areas[:1]))


def _ownership_claims(rows: Sequence[Dict[str, Any]], leaver_name: str) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for row in rows[:5]:
        share = row["share"]
        if share >= 0.999 and row["total_commits"] >= 3:
            qualifier = " — the only committer in this window"
        elif share >= 0.6:
            qualifier = " — a single-owner dependency"
        else:
            qualifier = ""
        claims.append(
            _claim(
                "owned_areas",
                "%s wrote %d of %d commits touching %s (%.0f%%)%s."
                % (
                    leaver_name,
                    row["leaver_commits"],
                    row["total_commits"],
                    taxonomy.label(row["area"]),
                    share * 100,
                    qualifier,
                ),
                row["evidence_ids"],
            )
        )
    return claims


def _open_work_claims(rows: Sequence[Dict[str, Any]], leaver_name: str) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for row in rows[:8]:
        status = {
            "in_progress": "in progress",
            "open": "open",
            "blocked": "blocked",
            "waiting": "waiting",
        }.get(row["status"], row["status"] or "open")
        due = ", due %s" % row["due"] if row.get("due") else ""
        claims.append(
            _claim(
                "open_work",
                "“%s” — %s %s%s, still owned by %s." % (row["title"], status, row["kind"], due, leaver_name),
                [row["evidence_id"]],
            )
        )
    return claims


def _people_claims(rows: Sequence[Dict[str, Any]], leaver_name: str) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for position, row in enumerate(rows[:5]):
        record_word = "record" if row["records"] == 1 else "records"
        if position == 0:
            phrasing = "%s is the closest context holder after %s: %d %s across %s." % (
                row["name"],
                leaver_name,
                row["records"],
                record_word,
                _area_phrase(row["areas"]),
            )
        else:
            phrasing = "%s also holds context: %d %s across %s." % (
                row["name"],
                row["records"],
                record_word,
                _area_phrase(row["areas"]),
            )
        claims.append(_claim("people", phrasing, row["evidence_ids"]))
    return claims


# --------------------------------------------------------------------------- offline drafting
def _sentences(text: str) -> List[str]:
    return [piece.strip() for piece in SENTENCE_RE.split(text or "") if piece and piece.strip()]


def _quote(sentence: str) -> str:
    cleaned = " ".join(sentence.split())
    if len(cleaned) > QUOTE_CHARS:
        cleaned = cleaned[: QUOTE_CHARS - 1].rstrip() + "…"
    return cleaned.replace("“", '"').replace("”", '"')


def _attribution(item: Dict[str, Any]) -> str:
    author = item.get("author") or "unattributed"
    label = item.get("source_label") or item.get("source_type")
    stamp = (item.get("occurred_at") or "")[:10]
    bits = [author, str(label)]
    if stamp:
        bits.append(stamp)
    return " — %s" % ", ".join(bits)


SOURCE_PRIORITY = {
    "pull_request": 0,
    "document": 1,
    "meeting_note": 2,
    "chat": 3,
    "review": 4,
    "git_commit": 5,
    "issue": 6,
    "task": 7,
}


def _offline_narrative(
    evidence: Sequence[Dict[str, Any]], section: str, used: set
) -> Tuple[List[Dict[str, Any]], set]:
    cue_re = DECISION_CUE_RE if section == "decisions" else GOTCHA_CUE_RE
    candidates = sorted(
        evidence,
        key=lambda item: (
            SOURCE_PRIORITY.get(item.get("source_type"), 9),
            -(len(item.get("body") or "")),
            item.get("id") or "",
        ),
    )
    claims: List[Dict[str, Any]] = []
    seen_text: set = set()
    for item in candidates:
        body = item.get("body") or ""
        if len(body) < 40:
            continue
        for sentence in _sentences(body):
            lowered = sentence.lower()
            if len(sentence) < 35 or not cue_re.search(sentence):
                continue
            key = re.sub(r"[^a-z0-9]+", " ", lowered).strip()[:160]
            if key in used or key in seen_text:
                continue
            seen_text.add(key)
            used.add(key)
            claims.append(
                _claim(
                    section,
                    "“%s”%s" % (_quote(sentence), _attribution(item)),
                    [item["id"]],
                    origin="rules",
                    claim_type="quote",
                    verification="verbatim",
                    note="Verbatim excerpt selected by rule; open the citation to read the full record.",
                )
            )
            break
        limit = 7 if section == "decisions" else 6
        if len(claims) >= limit:
            break
    return claims, used


def _offline_first_week(
    evidence: Sequence[Dict[str, Any]],
    ownership_rows: Sequence[Dict[str, Any]],
    open_rows: Sequence[Dict[str, Any]],
    people_rows: Sequence[Dict[str, Any]],
    leaver_name: str,
) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    docs = [item for item in evidence if item.get("source_type") == "document"][:2]

    if docs:
        titles = " and ".join("“%s”" % doc.get("title") for doc in docs)
        claims.append(
            _claim(
                "first_week",
                "Day 1: read %s before changing anything in %s."
                % (titles, _content_areas(docs[0].get("areas") or [])),
                [doc["id"] for doc in docs],
                claim_type="plan",
                verification="template",
                note="Sequenced from the cited documents.",
            )
        )

    if people_rows:
        person = people_rows[0]
        claims.append(
            _claim(
                "first_week",
                "Day 1–2: sit with %s (%d shared records in %s) and walk the current state."
                % (person["name"], person["records"], _area_phrase(person["areas"])),
                person["evidence_ids"],
                claim_type="plan",
                verification="template",
                note="Chosen from the people-with-context ranking.",
            )
        )

    for row in open_rows[:4]:
        due = " (due %s)" % row["due"] if row.get("due") else ""
        claims.append(
            _claim(
                "first_week",
                "Day 2–5: take over “%s” — currently %s%s — and confirm its status with %s."
                % (row["title"], row["status"].replace("_", " "), due, leaver_name),
                [row["evidence_id"]],
                claim_type="plan",
                verification="template",
                note="Derived from the open-work list.",
            )
        )

    if ownership_rows:
        top = ownership_rows[0]
        claims.append(
            _claim(
                "first_week",
                "Week 1: keep changes to %s behind review — %s holds %.0f%% of its commits%s."
                % (
                    taxonomy.label(top["area"]),
                    leaver_name,
                    top["share"] * 100,
                    " and no other committer appears in this window" if top["share"] >= 0.999 else "",
                ),
                top["evidence_ids"],
                claim_type="plan",
                verification="template",
                note="Derived from the ownership share.",
            )
        )
    return claims


# --------------------------------------------------------------------------- model drafting
DRAFTER_SYSTEM = (
    "You write an engineering handover that must be auditable. "
    "Every sentence you write has to be supported by the evidence records given to you, and each claim "
    "must cite the ids of the records that support it. You never invent names, dates, numbers, ticket "
    "numbers, URLs or causes. If the evidence does not support a useful claim, write fewer claims. "
    "Reply with JSON only."
)


def _evidence_context(evidence: Sequence[Dict[str, Any]], budget: int = 10000) -> str:
    ranked = sorted(
        evidence,
        key=lambda item: (SOURCE_PRIORITY.get(item.get("source_type"), 9), -(len(item.get("body") or ""))),
    )
    blocks: List[str] = []
    used = 0
    for item in ranked:
        body = " ".join((item.get("body") or "").split())[:520]
        if not body:
            continue
        block = "[%s] type=%s date=%s author=%s title=%s\n%s" % (
            item["id"],
            item.get("source_type"),
            (item.get("occurred_at") or "unknown")[:10],
            item.get("author") or "unknown",
            item.get("title") or "",
            body,
        )
        if used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _draft_with_model(
    evidence: Sequence[Dict[str, Any]],
    leaver_name: str,
    window_start: Optional[str],
    window_end: Optional[str],
    stats: Dict[str, Any],
    open_rows: Sequence[Dict[str, Any]],
    people_rows: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], str]:
    context = _evidence_context(evidence)
    if not context:
        return [], "No evidence to draft from."

    known_ids = {item["id"] for item in evidence}

    def build_prompt(ctx: str) -> str:
        return (
            "Leaver: %s\nWindow: %s to %s\nAreas: %s\n"
            "Open work already computed by rules: %s\nColleagues with context: %s\n\n"
            "Write handover claims in exactly these sections: decisions, gotchas, first_week.\n"
            "Rules:\n"
            "- Only state what the evidence below supports. Quote or closely paraphrase; never strengthen it.\n"
            "- Cite 1 to 3 evidence ids per claim, using ids that appear in square brackets below.\n"
            "- Max 240 characters per claim. No markdown. No bullet characters inside the text.\n"
            "- decisions: why the system is built this way (tradeoffs, constraints, sign-offs, gates).\n"
            "- gotchas: landmines, manual steps, stale documentation, known unfixed issues.\n"
            "- first_week: 4 to 6 sequenced steps for the successor, each citing the record that justifies it.\n"
            "- If you cannot support a section, return an empty list for it.\n\n"
            'Return JSON: {"claims":[{"section":"decisions","text":"...","evidence_ids":["EV-0001"]}]}\n\n'
            "EVIDENCE:\n%s"
            % (
                leaver_name,
                (window_start or stats.get("first_seen") or "")[:10],
                (window_end or stats.get("last_seen") or "")[:10],
                _area_phrase(stats.get("areas") or []),
                "; ".join(row["title"] or "" for row in open_rows[:6]) or "none",
                ", ".join(row["name"] for row in people_rows[:4]) or "none",
                ctx,
            )
        )

    result = llm.complete(DRAFTER_SYSTEM, build_prompt(context), max_tokens=config.LLM_MAX_OUTPUT_TOKENS)
    if not result.ok:
        # Retry once with a smaller context: reasoning models can spend the whole budget
        # thinking about a long prompt and return no text at all.
        smaller = _evidence_context(evidence, budget=6000)
        if smaller and smaller != context:
            result = llm.complete(
                DRAFTER_SYSTEM, build_prompt(smaller), max_tokens=config.LLM_MAX_OUTPUT_TOKENS
            )
    if not result.ok:
        return [], "Model drafting unavailable (%s). Used the deterministic extractor instead." % (
            result.error or "no key"
        )

    parsed = llm.parse_json_object(result.text)
    if not parsed or not isinstance(parsed.get("claims"), list):
        return [], "Model returned an unusable draft. Used the deterministic extractor instead."

    claims: List[Dict[str, Any]] = []
    per_section: Dict[str, int] = {}
    for raw in parsed["claims"]:
        if not isinstance(raw, dict):
            continue
        section = str(raw.get("section") or "").strip().lower()
        text = " ".join(str(raw.get("text") or "").split())
        ids = raw.get("evidence_ids")
        if section not in NARRATIVE_SECTIONS or len(text) < 25 or not isinstance(ids, list):
            continue
        valid_ids = [str(evidence_id) for evidence_id in ids if str(evidence_id) in known_ids][:3]
        if not valid_ids:
            continue
        if per_section.get(section, 0) >= 6:
            continue
        per_section[section] = per_section.get(section, 0) + 1
        claims.append(
            _claim(
                section,
                text[:400],
                valid_ids,
                origin="model",
                claim_type="model",
                verification="llm",
                note="Drafted by %s (%s) from the cited records." % (result.provider, result.model),
            )
        )
    if not claims:
        return [], "Model produced no usable claims. Used the deterministic extractor instead."
    return claims, "Drafted with %s (%s); citations were verified before review." % (result.provider, result.model)


def _dedupe(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for claim in claims:
        key = re.sub(r"[^a-z0-9]+", " ", (claim.get("text") or "").lower()).strip()[:200]
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(claim)
    return unique
