"""Storage layer: SQLAlchemy Core with raw SQL, portable across SQLite and Postgres."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from . import config

_engine: Optional[Engine] = None

SCHEMA: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        mode TEXT NOT NULL,
        project_name TEXT,
        repo_full_name TEXT,
        leaver_name TEXT,
        leaver_email TEXT,
        window_start TEXT,
        window_end TEXT,
        status TEXT NOT NULL,
        llm_status TEXT NOT NULL,
        llm_note TEXT,
        summary_json TEXT NOT NULL,
        expires_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_label TEXT,
        external_id TEXT,
        title TEXT,
        body TEXT,
        author TEXT,
        occurred_at TEXT,
        url TEXT,
        areas TEXT NOT NULL,
        metadata TEXT NOT NULL,
        ordinal INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS claims (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        section TEXT NOT NULL,
        text TEXT NOT NULL,
        claim_type TEXT NOT NULL,
        confidence TEXT NOT NULL,
        evidence_ids TEXT NOT NULL,
        origin TEXT NOT NULL,
        verification TEXT NOT NULL,
        verification_note TEXT,
        status TEXT NOT NULL,
        final_text TEXT,
        note TEXT,
        ordinal INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        action TEXT NOT NULL,
        at TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS coverage_gaps (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        area TEXT NOT NULL,
        evidence_count INTEGER NOT NULL,
        reason TEXT NOT NULL,
        evidence_ids TEXT NOT NULL,
        ordinal INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS handovers (
        token TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        approved_count INTEGER NOT NULL,
        rejected_count INTEGER NOT NULL,
        pending_count INTEGER NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_budget (
        day TEXT PRIMARY KEY,
        calls INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_evidence_session ON evidence (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_claims_session ON claims (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_decisions_session ON decisions (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_gaps_session ON coverage_gaps (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_handovers_session ON handovers (session_id)",
]


def engine() -> Engine:
    global _engine
    if _engine is None:
        url = config.DATABASE_URL
        kwargs: Dict[str, Any] = {"pool_pre_ping": True, "future": True}
        if url.startswith("sqlite"):
            path = config.sqlite_path()
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 20}
        _engine = create_engine(url, **kwargs)
    return _engine


def init_db() -> None:
    with engine().begin() as conn:
        for statement in SCHEMA:
            conn.execute(text(statement))


def query(sql: str, **params: Any) -> List[Dict[str, Any]]:
    with engine().connect() as conn:
        result = conn.execute(text(sql), params)
        return [dict(row._mapping) for row in result]


def query_one(sql: str, **params: Any) -> Optional[Dict[str, Any]]:
    rows = query(sql, **params)
    return rows[0] if rows else None


def execute(sql: str, **params: Any) -> None:
    with engine().begin() as conn:
        conn.execute(text(sql), params)


def execute_many(sql: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    with engine().begin() as conn:
        conn.execute(text(sql), rows)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def expiry_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=config.SESSION_TTL_HOURS)).replace(microsecond=0).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default if default is not None else []


def reserve_llm_call() -> bool:
    """Atomically reserve one model call for today. Returns False when the cap is hit."""
    day = datetime.now(timezone.utc).date().isoformat()
    with engine().begin() as conn:
        row = conn.execute(text("SELECT calls FROM llm_budget WHERE day = :day"), {"day": day}).fetchone()
        current = int(row[0]) if row else 0
        if current >= config.DAILY_LLM_CALL_CAP:
            return False
        if row is None:
            conn.execute(text("INSERT INTO llm_budget (day, calls) VALUES (:day, 1)"), {"day": day})
        else:
            conn.execute(text("UPDATE llm_budget SET calls = :calls WHERE day = :day"), {"calls": current + 1, "day": day})
    return True


def llm_calls_today() -> int:
    day = datetime.now(timezone.utc).date().isoformat()
    row = query_one("SELECT calls FROM llm_budget WHERE day = :day", day=day)
    return int(row["calls"]) if row else 0


def purge_expired() -> int:
    """Delete sessions past their TTL. Called opportunistically, never on the hot path."""
    cutoff = now_iso()
    expired = query("SELECT id FROM sessions WHERE expires_at IS NOT NULL AND expires_at < :cutoff", cutoff=cutoff)
    for row in expired:
        sid = row["id"]
        # Signed handovers outlive the run: they are the shareable artefact and contain only
        # approved claims plus short excerpts, not the uploaded chat corpus.
        for table in ("evidence", "claims", "decisions", "coverage_gaps"):
            execute("DELETE FROM {} WHERE session_id = :sid".format(table), sid=sid)
        execute("DELETE FROM sessions WHERE id = :sid", sid=sid)
    return len(expired)


def purge_handovers(older_than_days: int) -> int:
    """Signed handovers are kept for a bounded window, then removed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).replace(microsecond=0).isoformat()
    rows = query("SELECT token FROM handovers WHERE created_at < :cutoff", cutoff=cutoff)
    for row in rows:
        execute("DELETE FROM handovers WHERE token = :token", token=row["token"])
    return len(rows)
