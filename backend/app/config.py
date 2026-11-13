"""Single source of truth for configuration and the handover section order."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

APP_NAME = "Handover Lens"
APP_VERSION = "1.0.0"


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


DATA_DIR = Path(os.environ.get("HANDOVER_DATA_DIR") or (ROOT / "data")).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip() or ("sqlite:///" + str(DATA_DIR / "handover.db"))

SESSION_TTL_HOURS = _int("SESSION_TTL_HOURS", 72)

MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_BYTES", 2_000_000)
MAX_UPLOAD_FILES = _int("MAX_UPLOAD_FILES", 8)
MAX_TOTAL_UPLOAD_BYTES = _int("MAX_TOTAL_UPLOAD_BYTES", 6_000_000)

RATE_LIMIT_PER_MINUTE = _int("RATE_LIMIT_PER_MINUTE", 120)
HEAVY_RATE_LIMIT_PER_MINUTE = _int("HEAVY_RATE_LIMIT_PER_MINUTE", 8)
MAX_CONCURRENT_GENERATIONS = _int("MAX_CONCURRENT_GENERATIONS", 2)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_MAX_COMMITS = _int("GITHUB_MAX_COMMITS", 120)
GITHUB_MAX_PULLS = _int("GITHUB_MAX_PULLS", 80)
GITHUB_MAX_COMMIT_DETAIL = _int("GITHUB_MAX_COMMIT_DETAIL", 40)
GITHUB_TIMEOUT_SECONDS = _int("GITHUB_TIMEOUT_SECONDS", 20)

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto").strip().lower()
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
# Groq's keys use the gsk_ prefix; GROK_API_KEY is accepted as an alias because that is
# how they are usually labelled.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip() or os.environ.get("GROK_API_KEY", "").strip()
XAI_API_KEY = os.environ.get("XAI_API_KEY", "").strip()
LLM_TIMEOUT_SECONDS = _int("LLM_TIMEOUT_SECONDS", 45)
LLM_MAX_OUTPUT_TOKENS = _int("LLM_MAX_OUTPUT_TOKENS", 2600)
DAILY_LLM_CALL_CAP = _int("DAILY_LLM_CALL_CAP", 400)

TRUST_PROXY = _bool("TRUST_PROXY", True)

# Ordered. The frontend renders exactly this order and labels.
SECTIONS: List[Dict[str, str]] = [
    {"key": "snapshot", "label": "Snapshot", "blurb": "Who is leaving, over what period, and where they worked."},
    {"key": "owned_areas", "label": "Owned areas", "blurb": "What this person actually carries, by share of commits."},
    {"key": "open_work", "label": "Open work", "blurb": "Anything still open and owned by the leaver."},
    {"key": "decisions", "label": "Decisions and rationale", "blurb": "Why the system looks the way it does."},
    {"key": "people", "label": "People to ask", "blurb": "Who else holds context, and what to ask them."},
    {"key": "gotchas", "label": "Gotchas and undocumented areas", "blurb": "Landmines, manual steps and thin documentation."},
    {"key": "first_week", "label": "First-week plan", "blurb": "A sequenced start for the successor, built from the above."},
]

SECTION_KEYS = [s["key"] for s in SECTIONS]
SECTION_LABELS = {s["key"]: s["label"] for s in SECTIONS}

CLAIM_STATUSES = ["pending", "approved", "edited", "rejected", "needs_confirmation", "dropped"]
REVIEW_ACTIONS = ["approve", "edit", "reject", "needs_confirmation", "reopen"]

MAX_CLAIM_CHARS = 1200
MAX_NOTE_CHARS = 600
MAX_EVIDENCE_BODY_CHARS = 6000


PROVIDER_ORDER = ("groq", "gemini", "openai", "anthropic", "xai")

DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "xai": "grok-3-mini",
    "offline": "rule-based-drafter",
}


def _provider_keys() -> Dict[str, str]:
    return {
        "groq": GROQ_API_KEY,
        "gemini": GEMINI_API_KEY,
        "openai": OPENAI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
        "xai": XAI_API_KEY,
    }


def llm_config() -> Dict[str, Any]:
    """Resolved provider settings. Never exposes key material."""
    keys = _provider_keys()
    configured = {name: bool(keys[name]) for name in PROVIDER_ORDER}
    if LLM_PROVIDER in configured and configured[LLM_PROVIDER]:
        provider = LLM_PROVIDER
    elif LLM_PROVIDER == "offline":
        provider = "offline"
    else:
        provider = next((name for name in PROVIDER_ORDER if configured[name]), "offline")
    return {
        "provider": provider,
        "model": LLM_MODEL or DEFAULT_MODELS[provider],
        "configured": provider != "offline",
        "raw_provider_env": LLM_PROVIDER,
        "daily_call_cap": DAILY_LLM_CALL_CAP,
    }


def public_limits() -> Dict[str, Any]:
    return {
        "upload_mb_per_file": round(MAX_UPLOAD_BYTES / 1_000_000, 1),
        "upload_mb_per_request": round(MAX_TOTAL_UPLOAD_BYTES / 1_000_000, 1),
        "upload_files": MAX_UPLOAD_FILES,
        "commits_read": GITHUB_MAX_COMMITS,
        "pulls_read": GITHUB_MAX_PULLS,
        "session_ttl_hours": SESSION_TTL_HOURS,
        "heavy_requests_per_minute": HEAVY_RATE_LIMIT_PER_MINUTE,
    }


def database_is_sqlite() -> bool:
    return DATABASE_URL.startswith("sqlite")


def sqlite_path() -> Optional[Path]:
    if not database_is_sqlite():
        return None
    raw = DATABASE_URL.replace("sqlite:///", "", 1)
    return Path(raw)
