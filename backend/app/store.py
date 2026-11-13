"""Persistence helpers. Every route and the sample seeder go through this module."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import config, db, security

CLAIM_COLUMNS = (
    "id, session_id, section, text, claim_type, confidence, evidence_ids, origin, "
    "verification, verification_note, status, final_text, note, ordinal"
)
EVIDENCE_COLUMNS = (
    "id, session_id, source_type, source_label, external_id, title, body, author, "
    "occurred_at, url, areas, metadata, ordinal"
)


# --------------------------------------------------------------------------- sessions
def create_session(
    mode: str,
    project_name: str,
    leaver_name: str,
    leaver_email: str,
    window_start: Optional[str],
    window_end: Optional[str],
    repo_full_name: Optional[str],
    summary: Optional[Dict[str, Any]] = None,
    llm_status: str = "pending",
    llm_note: Optional[str] = None,
) -> str:
    session_id = security.new_session_id()
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO sessions (id, created_at, updated_at, mode, project_name, repo_full_name,
            leaver_name, leaver_email, window_start, window_end, status, llm_status, llm_note,
            summary_json, expires_at)
        VALUES (:id, :created_at, :updated_at, :mode, :project_name, :repo_full_name,
            :leaver_name, :leaver_email, :window_start, :window_end, :status, :llm_status, :llm_note,
            :summary_json, :expires_at)
        """,
        id=session_id,
        created_at=now,
        updated_at=now,
        mode=mode,
        project_name=security.clamp_text(project_name, 160),
        repo_full_name=repo_full_name,
        leaver_name=security.clamp_text(leaver_name, 120),
        leaver_email=security.clamp_text(leaver_email, 160),
        window_start=window_start,
        window_end=window_end,
        status="ingested",
        llm_status=llm_status,
        llm_note=llm_note,
        summary_json=db.dumps(summary or {}),
        expires_at=db.expiry_iso(),
    )
    return session_id


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    row = db.query_one("SELECT * FROM sessions WHERE id = :id", id=session_id)
    if not row:
        return None
    row["summary"] = db.loads(row.pop("summary_json", "{}"), {})
    return row


def update_session(session_id: str, **fields: Any) -> None:
    allowed = {"status", "llm_status", "llm_note", "summary_json", "leaver_name", "window_start", "window_end"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join("%s = :%s" % (key, key) for key in updates)
    updates["updated_at"] = db.now_iso()
    assignments += ", updated_at = :updated_at"
    updates["session_id"] = session_id
    db.execute("UPDATE sessions SET %s WHERE id = :session_id" % assignments, **updates)


def merge_summary(session_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    session = get_session(session_id)
    summary = (session or {}).get("summary") or {}
    summary.update(patch)
    update_session(session_id, summary_json=db.dumps(summary))
    return summary


def _next_id_number(table: str) -> int:
    """Evidence and claim ids are primary keys, so they must keep counting across the
    whole table rather than restarting inside every session."""
    row = db.query_one("SELECT MAX(CAST(SUBSTR(id, 4) AS INTEGER)) AS max_n FROM %s" % table)
    try:
        return int((row or {}).get("max_n") or 0) + 1
    except (TypeError, ValueError):
        return 1


# --------------------------------------------------------------------------- evidence
def insert_evidence(session_id: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not items:
        return []
    existing = db.query(
        "SELECT source_type, source_label, external_id FROM evidence WHERE session_id = :sid ORDER BY ordinal",
        sid=session_id,
    )
    seen = set()
    for row in existing:
        seen.add((row["source_type"], row["source_label"], row["external_id"]))
    next_number = _next_id_number("evidence")

    rows: List[Dict[str, Any]] = []
    stored: List[Dict[str, Any]] = []
    ordinal = len(existing)
    for item in items:
        key = (item.get("source_type"), item.get("source_label"), item.get("external_id"))
        if key in seen:
            continue
        seen.add(key)
        evidence_id = "EV-%04d" % next_number
        next_number += 1
        ordinal += 1
        row = {
            "id": evidence_id,
            "session_id": session_id,
            "source_type": security.clamp_text(item.get("source_type") or "document", 40),
            "source_label": security.clean_one_line(item.get("source_label"), 160),
            "external_id": security.clean_one_line(item.get("external_id"), 160),
            "title": security.clean_one_line(item.get("title"), 200),
            "body": security.clamp_text(item.get("body"), config.MAX_EVIDENCE_BODY_CHARS),
            "author": security.clean_one_line(item.get("author"), 120) or None,
            "occurred_at": security.clamp_text(item.get("occurred_at"), 40) or None,
            "url": _safe_url(item.get("url")),
            "areas": db.dumps(item.get("areas") or []),
            "metadata": db.dumps(item.get("metadata") or {}),
            "ordinal": ordinal,
        }
        rows.append(row)
        stored.append(_hydrate_evidence(row))

    if rows:
        db.execute_many(
            """
            INSERT INTO evidence (id, session_id, source_type, source_label, external_id, title, body,
                author, occurred_at, url, areas, metadata, ordinal)
            VALUES (:id, :session_id, :source_type, :source_label, :external_id, :title, :body,
                :author, :occurred_at, :url, :areas, :metadata, :ordinal)
            """,
            rows,
        )
    return stored


def _safe_url(value: Any) -> Optional[str]:
    url = str(value or "").strip()
    if not url:
        return None
    if not (url.startswith("https://") or url.startswith("http://")):
        return None
    return url[:500]


def _hydrate_evidence(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["areas"] = db.loads(item.get("areas"), [])
    item["metadata"] = db.loads(item.get("metadata"), {})
    return item


def list_evidence(session_id: str) -> List[Dict[str, Any]]:
    rows = db.query("SELECT %s FROM evidence WHERE session_id = :sid ORDER BY ordinal" % EVIDENCE_COLUMNS, sid=session_id)
    return [_hydrate_evidence(row) for row in rows]


def get_evidence(session_id: str, evidence_id: str) -> Optional[Dict[str, Any]]:
    row = db.query_one(
        "SELECT %s FROM evidence WHERE session_id = :sid AND id = :eid" % EVIDENCE_COLUMNS,
        sid=session_id,
        eid=evidence_id,
    )
    return _hydrate_evidence(row) if row else None


# --------------------------------------------------------------------------- claims
def _hydrate_claim(row: Dict[str, Any]) -> Dict[str, Any]:
    claim = dict(row)
    claim["evidence_ids"] = db.loads(claim.get("evidence_ids"), [])
    claim["confidence"] = claim.get("confidence") or "low"
    return claim


def replace_claims(session_id: str, claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    db.execute("DELETE FROM claims WHERE session_id = :sid", sid=session_id)
    db.execute("DELETE FROM coverage_gaps WHERE session_id = :sid", sid=session_id)
    db.execute("DELETE FROM decisions WHERE session_id = :sid", sid=session_id)

    rows = []
    first_id = _next_id_number("claims")
    for ordinal, claim in enumerate(claims, start=1):
        rows.append(
            {
                "id": "CL-%04d" % (first_id + ordinal - 1),
                "session_id": session_id,
                "section": claim["section"],
                "text": claim["text"],
                "claim_type": claim.get("claim_type") or "rule",
                "confidence": claim.get("confidence") or "medium",
                "evidence_ids": db.dumps(claim.get("evidence_ids") or []),
                "origin": claim.get("origin") or "rules",
                "verification": claim.get("verification") or "id-check",
                "verification_note": claim.get("verification_note"),
                "status": claim.get("status") or "pending",
                "final_text": claim.get("final_text"),
                "note": claim.get("note"),
                "ordinal": ordinal,
            }
        )
    if rows:
        db.execute_many(
            """
            INSERT INTO claims (id, session_id, section, text, claim_type, confidence, evidence_ids,
                origin, verification, verification_note, status, final_text, note, ordinal)
            VALUES (:id, :session_id, :section, :text, :claim_type, :confidence, :evidence_ids,
                :origin, :verification, :verification_note, :status, :final_text, :note, :ordinal)
            """,
            rows,
        )
        return [_hydrate_claim(row) for row in rows]
    return []


def list_claims(session_id: str, include_dropped: bool = True) -> List[Dict[str, Any]]:
    sql = "SELECT %s FROM claims WHERE session_id = :sid" % CLAIM_COLUMNS
    if not include_dropped:
        sql += " AND status != 'dropped'"
    sql += " ORDER BY ordinal"
    return [_hydrate_claim(row) for row in db.query(sql, sid=session_id)]


def get_claim(session_id: str, claim_id: str) -> Optional[Dict[str, Any]]:
    row = db.query_one(
        "SELECT %s FROM claims WHERE session_id = :sid AND id = :cid" % CLAIM_COLUMNS, sid=session_id, cid=claim_id
    )
    return _hydrate_claim(row) if row else None


def update_claim_status(
    session_id: str,
    claim_id: str,
    status: str,
    final_text: Optional[str],
    note: Optional[str],
) -> None:
    db.execute(
        "UPDATE claims SET status = :status, final_text = :final_text, note = :note WHERE session_id = :sid AND id = :cid",
        status=status,
        final_text=final_text,
        note=note,
        sid=session_id,
        cid=claim_id,
    )


def approved_claims(session_id: str) -> List[Dict[str, Any]]:
    claims = list_claims(session_id, include_dropped=False)
    return [claim for claim in claims if claim["status"] in ("approved", "edited")]


# --------------------------------------------------------------------------- decisions
def add_decision(session_id: str, claim_id: str, action: str, reviewer: str, note: Optional[str]) -> Dict[str, Any]:
    row = {
        "id": security.new_id("dec", 6),
        "session_id": session_id,
        "claim_id": claim_id,
        "action": action,
        "at": db.now_iso(),
        "reviewer": reviewer,
        "note": note,
    }
    db.execute(
        "INSERT INTO decisions (id, session_id, claim_id, action, at, reviewer, note) "
        "VALUES (:id, :session_id, :claim_id, :action, :at, :reviewer, :note)",
        **row,
    )
    return row


def list_decisions(session_id: str) -> List[Dict[str, Any]]:
    return db.query("SELECT * FROM decisions WHERE session_id = :sid ORDER BY at, id", sid=session_id)


# --------------------------------------------------------------------------- coverage gaps
def replace_gaps(session_id: str, gaps: List[Dict[str, Any]]) -> None:
    db.execute("DELETE FROM coverage_gaps WHERE session_id = :sid", sid=session_id)
    rows = []
    for ordinal, gap in enumerate(gaps, start=1):
        rows.append(
            {
                "id": "%s-GAP-%02d" % (session_id, ordinal),
                "session_id": session_id,
                "area": gap["area"],
                "evidence_count": int(gap.get("evidence_count") or 0),
                "reason": gap["reason"],
                "evidence_ids": db.dumps(gap.get("evidence_ids") or []),
                "ordinal": ordinal,
            }
        )
    if rows:
        db.execute_many(
            "INSERT INTO coverage_gaps (id, session_id, area, evidence_count, reason, evidence_ids, ordinal) "
            "VALUES (:id, :session_id, :area, :evidence_count, :reason, :evidence_ids, :ordinal)",
            rows,
        )


def list_gaps(session_id: str) -> List[Dict[str, Any]]:
    rows = db.query("SELECT * FROM coverage_gaps WHERE session_id = :sid ORDER BY ordinal", sid=session_id)
    for row in rows:
        row["evidence_ids"] = db.loads(row.get("evidence_ids"), [])
    return rows


# --------------------------------------------------------------------------- handovers
def create_handover(
    session_id: str,
    reviewer: str,
    payload: Dict[str, Any],
    fingerprint: str,
    counts: Dict[str, int],
) -> str:
    token = security.new_token()
    db.execute(
        """
        INSERT INTO handovers (token, session_id, created_at, reviewer, fingerprint,
            approved_count, rejected_count, pending_count, payload)
        VALUES (:token, :session_id, :created_at, :reviewer, :fingerprint,
            :approved_count, :rejected_count, :pending_count, :payload)
        """,
        token=token,
        session_id=session_id,
        created_at=db.now_iso(),
        reviewer=reviewer,
        fingerprint=fingerprint,
        approved_count=counts.get("approved", 0),
        rejected_count=counts.get("rejected", 0),
        pending_count=counts.get("pending", 0),
        payload=db.dumps(payload),
    )
    return token


def get_handover(token: str) -> Optional[Dict[str, Any]]:
    row = db.query_one("SELECT * FROM handovers WHERE token = :token", token=token)
    if not row:
        return None
    row["payload"] = db.loads(row.get("payload"), {})
    return row


def list_handovers(session_id: str) -> List[Dict[str, Any]]:
    rows = db.query(
        "SELECT token, created_at, reviewer, fingerprint, approved_count FROM handovers "
        "WHERE session_id = :sid ORDER BY created_at DESC",
        sid=session_id,
    )
    return rows


# --------------------------------------------------------------------------- assembled view
def evidence_summary(item: Dict[str, Any], limit: int = 320) -> Dict[str, Any]:
    body = item.get("body") or ""
    snippet = " ".join(body.split())
    if len(snippet) > limit:
        snippet = snippet[: limit - 1].rstrip() + "…"
    return {
        "id": item["id"],
        "source_type": item["source_type"],
        "source_label": item.get("source_label"),
        "external_id": item.get("external_id"),
        "title": item.get("title"),
        "author": item.get("author"),
        "occurred_at": item.get("occurred_at"),
        "url": item.get("url"),
        "areas": item.get("areas") or [],
        "snippet": snippet,
    }


def session_payload(session_id: str) -> Optional[Dict[str, Any]]:
    session = get_session(session_id)
    if not session:
        return None
    evidence = list_evidence(session_id)
    claims = list_claims(session_id)
    gaps = list_gaps(session_id)
    decisions = list_decisions(session_id)

    visible = [claim for claim in claims if claim["status"] != "dropped"]
    counts = {
        "evidence": len(evidence),
        "claims": len(visible),
        "approved": sum(1 for c in claims if c["status"] == "approved"),
        "edited": sum(1 for c in claims if c["status"] == "edited"),
        "rejected": sum(1 for c in claims if c["status"] == "rejected"),
        "needs_confirmation": sum(1 for c in claims if c["status"] == "needs_confirmation"),
        "pending": sum(1 for c in claims if c["status"] == "pending"),
        "dropped": sum(1 for c in claims if c["status"] == "dropped"),
        "reviewed": sum(1 for c in claims if c["status"] in ("approved", "edited", "rejected", "needs_confirmation")),
    }

    return {
        "session": {
            "id": session["id"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "mode": session["mode"],
            "project_name": session["project_name"],
            "repo_full_name": session["repo_full_name"],
            "leaver_name": session["leaver_name"],
            "leaver_email": session["leaver_email"],
            "window_start": session["window_start"],
            "window_end": session["window_end"],
            "status": session["status"],
            "llm_status": session["llm_status"],
            "llm_note": session["llm_note"],
            "expires_at": session["expires_at"],
            "summary": session.get("summary") or {},
        },
        "sections": config.SECTIONS,
        "evidence": [evidence_summary(item) for item in evidence],
        "claims": claims,
        "gaps": gaps,
        "decisions": decisions,
        "handovers": list_handovers(session_id),
        "counts": counts,
    }


def evidence_lookup(session_id: str) -> Dict[str, Dict[str, Any]]:
    return {item["id"]: item for item in list_evidence(session_id)}


def search_evidence(
    session_id: str,
    query: str = "",
    area: str = "",
    source: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Filtered, paginated evidence lookup. Values are bound parameters, never interpolated."""
    clauses = ["session_id = :sid"]
    params: Dict[str, Any] = {"sid": session_id}

    needle = (query or "").strip().lower()[:120]
    if needle:
        clauses.append(
            "(lower(coalesce(title, '')) LIKE :needle"
            " OR lower(coalesce(body, '')) LIKE :needle"
            " OR lower(coalesce(author, '')) LIKE :needle"
            " OR lower(coalesce(source_label, '')) LIKE :needle)"
        )
        params["needle"] = "%" + needle + "%"

    area_key = "".join(char for char in (area or "") if char.isalnum() or char in "-_")
    if area_key:
        clauses.append("areas LIKE :area")
        params["area"] = '%"' + area_key + '"%'

    source_key = "".join(char for char in (source or "") if char.isalnum() or char == "_")
    if source_key:
        clauses.append("source_type = :source")
        params["source"] = source_key

    where = " AND ".join(clauses)
    total_row = db.query_one("SELECT COUNT(*) AS n FROM evidence WHERE " + where, **params)
    total = int((total_row or {}).get("n") or 0)
    rows = db.query(
        "SELECT * FROM evidence WHERE " + where + " ORDER BY occurred_at DESC, id DESC LIMIT :limit OFFSET :offset",
        limit=limit,
        offset=offset,
        **params,
    )
    return [_hydrate_evidence(row) for row in rows], total


def claim_counts(claims: List[Dict[str, Any]]) -> Tuple[Dict[str, int], Dict[str, int]]:
    statuses: Dict[str, int] = {}
    sections: Dict[str, int] = {}
    for claim in claims:
        statuses[claim["status"]] = statuses.get(claim["status"], 0) + 1
        sections[claim["section"]] = sections.get(claim["section"], 0) + 1
    return statuses, sections
