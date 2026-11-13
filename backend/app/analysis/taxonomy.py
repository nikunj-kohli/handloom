"""Topic taxonomy: rule-based area tagging shared by every ingester and the rules engine."""
from __future__ import annotations

import re
from typing import List, Sequence

# Order matters only for output stability. Each area has keywords plus path hints.
AREA_KEYWORDS = [
    ("billing-engine", ["charge", "proration", "invoice", "idempotency", "currency", "billing", "ledger entry"]),
    ("ledger", ["ledger", "double-entry", "replica", "batch", "lock contention", "posting", "month-end"]),
    ("refunds", ["refund", "chargeback", "settlement", "state machine", "partial refund", "runbook"]),
    ("webhooks", ["webhook", "dlq", "dead-letter", "signature", "retry", "backoff", "event delivery"]),
    ("pricing", ["pricing", "tier", "grandfather", "pricing v2", "flag", "memo"]),
    ("notifications", ["notification", "email digest", "digest", "throttle", "email provider"]),
    ("admin-tools", ["admin", "credit issuance", "audit trail"]),
    ("infra", ["terraform", "alert", "deploy", "replication", "dlq depth"]),
]

AREA_LABELS = {key: key.replace("-", " ").title() for key, _ in AREA_KEYWORDS}
AREA_LABELS.update({"docs": "Docs", "unclassified": "Unclassified"})

DOC_PATH_RE = re.compile(r"(^|/)(docs?|readme|runbooks?|adr)/|\.(md|markdown|rst)$", re.IGNORECASE)


def areas_from_paths(paths: Sequence[str]) -> List[str]:
    """Turn file paths into stable area keys (e.g. services/billing/charge.py → billing)."""
    areas: List[str] = []
    for path in paths:
        lowered = path.lower()
        if DOC_PATH_RE.search(lowered):
            _add(areas, "docs")
        match = re.match(r"^(?:services|apps|packages|src|lib|internal)/([a-z0-9_.-]+)", lowered)
        if match:
            _add(areas, _normalise_area(match.group(1)))
            continue
        if lowered.startswith(("infra/", "terraform/", ".github/workflows/")):
            _add(areas, "infra")
            continue
        if lowered.startswith(("jobs/", "scripts/", "tools/")):
            _add(areas, "infra")
    return areas


def _normalise_area(name: str) -> str:
    cleaned = name.replace("_", "-").strip("-")
    alias = {
        "billings": "billing-engine",
        "billing": "billing-engine",
        "refund": "refunds",
        "webhook": "webhooks",
        "notification": "notifications",
        "notifications-api": "notifications",
        "admin": "admin-tools",
    }
    return alias.get(cleaned, cleaned)


def _add(areas: List[str], area: str) -> None:
    if area and area not in areas:
        areas.append(area)


def infer_areas(text: str, paths: Sequence[str] = ()) -> List[str]:
    """Tag a free-text record with areas. Rule-based and deliberately boring."""
    found: List[str] = list(areas_from_paths(paths))
    haystack = (text or "").lower()
    if not haystack:
        return found[:4]
    for area, keywords in AREA_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            _add(found, area)
        if len(found) >= 4:
            break
    return found[:4]


def label(area: str) -> str:
    return AREA_LABELS.get(area, area.replace("-", " ").title())
