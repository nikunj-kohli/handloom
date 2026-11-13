"""Every HTTP route. No accounts: a session id is an unguessable capability."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import config, db, llm, security, store
from .analysis import claims as claim_engine
from .analysis import export as export_engine
from .analysis import taxonomy
from .ingest import files as file_ingest
from .ingest import github
from .sample import data as sample_data
from .sample import seed as sample_seed

logger = logging.getLogger("handover.api")

router = APIRouter(prefix="/api")

# Signed share links must survive the run that produced them, or a link shared on Friday
# would 404 on Saturday. The full evidence corpus is still deleted with the run.
HANDOVER_RETENTION_DAYS = 14

_last_purge = 0.0


class GenerateRequest(BaseModel):
    force: bool = False


class DecisionRequest(BaseModel):
    action: str
    text: Optional[str] = None
    note: Optional[str] = None
    reviewer: Optional[str] = None


class HandoverRequest(BaseModel):
    reviewer: Optional[str] = None


# --------------------------------------------------------------------------- helpers
def _maybe_purge() -> None:
    global _last_purge
    now = time.time()
    if now - _last_purge < 600:
        return
    _last_purge = now
    try:
        removed = db.purge_expired()
        expired_handovers = db.purge_handovers(HANDOVER_RETENTION_DAYS)
        if removed or expired_handovers:
            logger.info("purged %d expired sessions and %d old handovers", removed, expired_handovers)
    except Exception as exc:  # maintenance must never break a request
        logger.warning("expired-session purge failed: %s", exc)


def _require_session(session_id: str) -> Dict[str, Any]:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="That handover run does not exist. Start a new one.")
    expires_at = session.get("expires_at")
    if expires_at and expires_at < db.now_iso():
        raise HTTPException(status_code=410, detail="That run expired. Uploads are deleted after %d hours." % config.SESSION_TTL_HOURS)
    return session


def _require_payload(session_id: str) -> Dict[str, Any]:
    payload = store.session_payload(session_id)
    if not payload:
        raise HTTPException(status_code=404, detail="That handover run does not exist.")
    return payload


def _clean_reviewer(value: Optional[str]) -> str:
    label = security.clean_one_line(value, 80)
    if not label:
        return "Anonymous reviewer"
    label = re.sub(r"[^A-Za-z0-9 ._()@+-]", "", label).strip()
    return label or "Anonymous reviewer"


def _clean_window(value: str) -> Optional[str]:
    raw = (value or "").strip()
    if not raw:
        return None
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Dates must look like 2026-07-15.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _llm_state(result: Optional[Dict[str, Any]]) -> str:
    cfg = config.llm_config()
    if not cfg["configured"]:
        return "offline"
    if result is not None and result.get("llm_used"):
        return cfg["provider"]
    return "failed"


# --------------------------------------------------------------------------- meta
@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "storage": "postgres" if not config.database_is_sqlite() else "sqlite",
        "llm": llm.status(),
        "github_token": bool(config.GITHUB_TOKEN),
        "limits": config.public_limits(),
        "sections": config.SECTIONS,
    }


@router.get("/sample")
def sample_info() -> Dict[str, Any]:
    return sample_seed.describe()


# --------------------------------------------------------------------------- intake
@router.post("/sessions/sample")
def create_sample(request: Request) -> Dict[str, Any]:
    security.enforce_heavy_limit(request)
    _maybe_purge()
    session_id = sample_seed.create_sample_session()
    return _require_payload(session_id)


@router.post("/sessions/ingest")
def ingest_session(
    request: Request,
    repo_url: str = Form(""),
    leaver_name: str = Form(""),
    leaver_email: str = Form(""),
    window_start: str = Form(""),
    window_end: str = Form(""),
    project_name: str = Form(""),
    files: Optional[List[UploadFile]] = File(None),
) -> Dict[str, Any]:
    security.enforce_heavy_limit(request)
    _maybe_purge()

    leaver = security.clean_one_line(leaver_name, 120)
    if not leaver:
        raise HTTPException(status_code=400, detail="Name the person who is leaving — it is how activity is matched.")

    start = _clean_window(window_start)
    end = _clean_window(window_end)
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="The window ends before it starts.")

    uploads = [upload for upload in (files or []) if upload and (upload.filename or "").strip()]
    repo_input = (repo_url or "").strip()
    if not repo_input and not uploads:
        raise HTTPException(status_code=400, detail="Add a public repo URL, at least one file, or use the sample project.")

    warnings: List[str] = []
    evidence_items: List[Dict[str, Any]] = []
    repo_meta: Dict[str, Any] = {}
    resolved_repo: Optional[str] = None

    if uploads:
        try:
            items, upload_warnings = file_ingest.ingest_uploads(uploads)
        except file_ingest.IngestError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
        evidence_items.extend(items)
        warnings.extend(upload_warnings)

    if repo_input:
        try:
            items, repo_meta, repo_warnings = github.fetch_repo_evidence(
                repo_input, leaver, security.clean_one_line(leaver_email, 160), start, end
            )
        except github.GitHubError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
        evidence_items.extend(items)
        warnings.extend(repo_warnings)
        resolved_repo = repo_meta.get("repo_full_name")

    if not evidence_items:
        raise HTTPException(
            status_code=422,
            detail="Nothing usable came back. Check the repo and the files, or load the sample project.",
        )

    name = (
        security.clean_one_line(project_name, 160)
        or resolved_repo
        or "Handover for %s" % leaver
    )
    session_id = store.create_session(
        mode="live",
        project_name=name,
        leaver_name=leaver,
        leaver_email=security.clean_one_line(leaver_email, 160),
        window_start=start,
        window_end=end,
        repo_full_name=resolved_repo,
        summary={
            "origin": "live",
            "warnings": warnings,
            "repo": repo_meta,
            "uploads": [security.clean_one_line(upload.filename, 120) for upload in uploads],
        },
    )
    stored = store.insert_evidence(session_id, evidence_items)
    if not stored:
        raise HTTPException(status_code=422, detail="No new records to store. Try a wider date window.")

    store.merge_summary(session_id, {"stored_records": len(stored)})
    return _require_payload(session_id)


@router.get("/sessions/{session_id}")
def get_session_detail(session_id: str) -> Dict[str, Any]:
    _require_session(session_id)
    return _require_payload(session_id)


@router.get("/sessions/{session_id}/evidence")
def search_evidence(
    session_id: str,
    request: Request,
    q: str = "",
    area: str = "",
    source: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Searchable, paginated evidence. Capped so a list call can never return the whole corpus."""
    security.enforce_general_limit(request)
    _require_session(session_id)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    rows, total = store.search_evidence(
        session_id, query=q, area=area, source=source, limit=limit, offset=offset
    )
    return {
        "items": [store.evidence_summary(item) for item in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "query": q,
    }


@router.get("/sessions/{session_id}/evidence/{evidence_id}")
def get_evidence(session_id: str, evidence_id: str) -> Dict[str, Any]:
    _require_session(session_id)
    item = store.get_evidence(session_id, evidence_id)
    if not item:
        raise HTTPException(status_code=404, detail="That evidence record is not part of this run.")
    return {
        "id": item["id"],
        "source_type": item["source_type"],
        "source_label": item.get("source_label"),
        "external_id": item.get("external_id"),
        "title": item.get("title"),
        "body": item.get("body"),
        "author": item.get("author"),
        "occurred_at": item.get("occurred_at"),
        "url": item.get("url"),
        "areas": item.get("areas") or [],
        "area_labels": [taxonomy.label(area) for area in (item.get("areas") or [])],
        "metadata": item.get("metadata") or {},
    }


# --------------------------------------------------------------------------- generate
@router.post("/sessions/{session_id}/generate")
def generate(session_id: str, request: Request, body: Optional[GenerateRequest] = None) -> Dict[str, Any]:
    security.enforce_heavy_limit(request)
    _maybe_purge()
    session = _require_session(session_id)

    force = bool(body.force) if body else False
    existing = store.list_claims(session_id)
    if existing and not force:
        payload = _require_payload(session_id)
        payload["cached"] = True
        return payload

    if not security.GENERATION_SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="Two generations are already running. Try again in a few seconds.",
        )
    try:
        evidence = store.list_evidence(session_id)
        if not evidence:
            raise HTTPException(status_code=422, detail="This run has no evidence to draft from.")

        cfg = config.llm_config()
        result = claim_engine.build_claims(
            evidence=evidence,
            leaver_name=session.get("leaver_name") or "",
            leaver_email=session.get("leaver_email") or "",
            window_start=session.get("window_start"),
            window_end=session.get("window_end"),
            project_name=session.get("project_name") or "",
            use_llm=cfg["configured"],
        )

        store.replace_claims(session_id, result["claims"])
        store.replace_gaps(session_id, result["gaps"])
        store.update_session(
            session_id,
            status="generated",
            llm_status=_llm_state(result),
            llm_note=result.get("verification_note"),
        )
        store.merge_summary(
            session_id,
            {
                "generation": {
                    "at": db.now_iso(),
                    "llm_used": result.get("llm_used"),
                    "dropped": result.get("dropped"),
                    "verification_note": result.get("verification_note"),
                    "sections": result.get("sections"),
                    "supporting": result.get("supporting"),
                }
            },
        )
    finally:
        security.GENERATION_SLOTS.release()

    payload = _require_payload(session_id)
    payload["cached"] = False
    return payload


# --------------------------------------------------------------------------- review
@router.post("/sessions/{session_id}/claims/{claim_id}/decision")
def decide(session_id: str, claim_id: str, body: DecisionRequest) -> Dict[str, Any]:
    _require_session(session_id)
    claim = store.get_claim(session_id, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="That claim is not part of this run.")
    if claim["status"] == "dropped":
        raise HTTPException(status_code=409, detail="The citation verifier dropped this claim; it cannot be approved.")
    if body.action not in config.REVIEW_ACTIONS:
        raise HTTPException(status_code=400, detail="Unknown review action.")

    reviewer = _clean_reviewer(body.reviewer)
    note = security.clamp_text(body.note, config.MAX_NOTE_CHARS) or None

    if body.action == "approve":
        status, final_text = "approved", None
    elif body.action == "edit":
        edited = security.clamp_text(body.text, config.MAX_CLAIM_CHARS)
        if len(edited) < 8:
            raise HTTPException(status_code=400, detail="An edited claim needs some text.")
        status, final_text = "edited", edited
    elif body.action == "reject":
        status, final_text = "rejected", None
    elif body.action == "needs_confirmation":
        status, final_text = "needs_confirmation", None
    else:
        status, final_text = "pending", None

    store.update_claim_status(session_id, claim_id, status, final_text, note)
    store.add_decision(session_id, claim_id, body.action, reviewer, note)

    updated = store.get_claim(session_id, claim_id)
    claims = store.list_claims(session_id)
    counts = {
        "approved": sum(1 for c in claims if c["status"] == "approved"),
        "edited": sum(1 for c in claims if c["status"] == "edited"),
        "rejected": sum(1 for c in claims if c["status"] == "rejected"),
        "needs_confirmation": sum(1 for c in claims if c["status"] == "needs_confirmation"),
        "pending": sum(1 for c in claims if c["status"] == "pending"),
        "dropped": sum(1 for c in claims if c["status"] == "dropped"),
        "reviewed": sum(
            1 for c in claims if c["status"] in ("approved", "edited", "rejected", "needs_confirmation")
        ),
    }
    return {"claim": updated, "counts": counts, "decisions": store.list_decisions(session_id)}


# --------------------------------------------------------------------------- export
@router.post("/sessions/{session_id}/handover")
def sign_handover(session_id: str, request: Request, body: Optional[HandoverRequest] = None) -> Dict[str, Any]:
    security.enforce_heavy_limit(request)
    session = _require_session(session_id)

    claims = store.list_claims(session_id)
    if not claims:
        raise HTTPException(status_code=409, detail="Generate the handover before signing it.")
    approved = [claim for claim in claims if claim["status"] in ("approved", "edited")]
    if not approved:
        raise HTTPException(status_code=400, detail="Approve or edit at least one claim first — the export only contains decisions you made.")

    reviewer = _clean_reviewer(body.reviewer if body else None)
    gaps = store.list_gaps(session_id)
    decisions = store.list_decisions(session_id)
    evidence_index = store.evidence_lookup(session_id)

    payload = export_engine.build_snapshot(
        session=session,
        claims=claims,
        gaps=gaps,
        decisions=decisions,
        evidence_index=evidence_index,
        reviewer=reviewer,
        signed_at=db.now_iso(),
    )
    counts = {
        "approved": payload["counts"]["approved"] + payload["counts"]["edited"],
        "rejected": payload["counts"]["rejected"],
        "pending": payload["counts"]["pending"],
    }
    token = store.create_handover(session_id, reviewer, payload, payload["fingerprint"], counts)
    store.update_session(session_id, status="signed")

    return {
        "token": token,
        "fingerprint": payload["fingerprint"],
        "counts": payload["counts"],
        "url": "/handover/%s" % token,
    }


def _load_handover(token: str) -> Dict[str, Any]:
    record = store.get_handover(token)
    if not record:
        raise HTTPException(status_code=404, detail="That shared handover does not exist.")
    return record


@router.get("/handover/{token}")
def get_handover(token: str) -> Dict[str, Any]:
    record = _load_handover(token)
    return {
        "token": token,
        "created_at": record["created_at"],
        "reviewer": record["reviewer"],
        "fingerprint": record["fingerprint"],
        "counts": {
            "approved": record["approved_count"],
            "rejected": record["rejected_count"],
            "pending": record["pending_count"],
        },
        "payload": record["payload"],
    }


@router.get("/handover/{token}/markdown")
def handover_markdown(token: str) -> PlainTextResponse:
    record = _load_handover(token)
    markdown = export_engine.render_markdown(record["payload"])
    filename = _download_name(record["payload"], "md")
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
    )


@router.get("/handover/{token}/pdf")
def handover_pdf(token: str) -> Response:
    record = _load_handover(token)
    try:
        pdf_bytes = export_engine.render_pdf(record["payload"])
    except ImportError:
        raise HTTPException(status_code=503, detail="PDF rendering is unavailable on this server; use the Markdown export.")
    filename = _download_name(record["payload"], "pdf")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="%s"' % filename,
            "Cache-Control": "no-store",
        },
    )


def _download_name(payload: Dict[str, Any], extension: str) -> str:
    leaver = security.clean_one_line(payload.get("leaver") or "handover", 60)
    slug = re.sub(r"[^a-z0-9]+", "-", leaver.lower()).strip("-") or "handover"
    return "handover-%s.%s" % (slug, extension)


@router.get("/handover/{token}/verify")
def verify_handover(token: str) -> Dict[str, Any]:
    record = _load_handover(token)
    payload = record["payload"]
    recomputed = export_engine.build_snapshot(
        session={
            "id": payload.get("session_id"),
            "project_name": payload.get("project"),
            "leaver_name": payload.get("leaver"),
            "repo_full_name": payload.get("repo"),
            "window_start": payload["window"].get("start"),
            "window_end": payload["window"].get("end"),
            "mode": payload.get("mode"),
            "updated_at": payload.get("generated_at"),
        },
        claims=[
            {
                "id": claim["id"],
                "section": section["key"],
                "text": claim.get("original_text") or claim["text"],
                "final_text": claim["text"] if claim.get("original_text") else None,
                "confidence": claim["confidence"],
                "claim_type": claim["claim_type"],
                "origin": claim["origin"],
                "verification": claim.get("verification"),
                "verification_note": claim.get("verification_note"),
                "note": claim.get("reviewer_note"),
                "status": claim["status"],
                "evidence_ids": [item["id"] for item in claim.get("evidence", [])],
            }
            for section in payload.get("sections", [])
            for claim in section["claims"]
        ],
        gaps=[
            {
                "area": gap["area"],
                "area_label": gap["label"],
                "reason": gap["reason"],
                "evidence_count": gap["evidence_count"],
                "evidence_ids": [item["id"] for item in gap.get("evidence", [])],
            }
            for gap in payload.get("gaps", [])
        ],
        decisions=[],
        evidence_index={
            item["id"]: item
            for section in payload.get("sections", [])
            for claim in section["claims"]
            for item in claim.get("evidence", [])
        },
        reviewer=payload.get("reviewer") or "",
        signed_at=payload.get("signed_at") or "",
    )
    return {
        "token": token,
        "stored_fingerprint": record["fingerprint"],
        "recomputed_fingerprint": recomputed["fingerprint"],
        "matches": recomputed["fingerprint"] == record["fingerprint"],
        "signed_at": payload.get("signed_at"),
        "reviewer": payload.get("reviewer"),
    }


@router.get("/sessions/{session_id}/traceability.csv")
def session_traceability(session_id: str, request: Request) -> Response:
    security.enforce_general_limit(request)
    session = _require_session(session_id)
    rows = export_engine.traceability_rows(store.list_claims(session_id), store.evidence_lookup(session_id))
    name = _download_name({"leaver": session.get("leaver_name")}, "csv")
    return Response(
        content=export_engine.render_traceability_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name, "Cache-Control": "no-store"},
    )


@router.get("/handover/{token}/traceability.csv")
def handover_traceability(token: str) -> Response:
    record = _load_handover(token)
    rows = export_engine.traceability_rows_from_payload(record["payload"])
    name = _download_name(record["payload"], "csv")
    return Response(
        content=export_engine.render_traceability_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="%s"' % name, "Cache-Control": "no-store"},
    )

