"""Rule-based extraction: who owns what, what is open, who to ask, what is uncovered.

Everything here is deterministic. These facts become the `high` confidence claims and
they also seed the coverage check, so a judge can compare rules against model output.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import taxonomy

COMMIT_SOURCES = ("git_commit",)
CHAT_SOURCES = ("chat",)
DOC_SOURCES = ("document", "meeting_note")
OPEN_TASK_STATUSES = ("open", "in_progress", "blocked", "waiting")

STOPWORD_AUTHORS = {"", "unknown", "github", "dependabot[bot]", "renovate[bot]", "ci", "bot"}


def normalise(value: Optional[str]) -> str:
    """Fold accents before stripping: 'Sebastián Ramírez' has to match 'Sebastian Ramirez'."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def names_match(left: Optional[str], right: Optional[str]) -> bool:
    a, b = normalise(left), normalise(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return a in b or b in a


def is_leaver(item: Dict[str, Any], leaver_name: str, leaver_email: str = "") -> bool:
    author = item.get("author")
    if not author:
        return False
    if names_match(author, leaver_name):
        return True
    login = (item.get("metadata") or {}).get("login")
    if login and names_match(login, leaver_name):
        return True
    return bool(leaver_email and leaver_email.lower() in str(author).lower())


def by_type(evidence: Sequence[Dict[str, Any]], types: Iterable[str]) -> List[Dict[str, Any]]:
    allowed = set(types)
    return [item for item in evidence if item.get("source_type") in allowed]


def sorted_by_time(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(item: Dict[str, Any]) -> Tuple[int, str]:
        stamp = item.get("occurred_at") or ""
        return (1 if stamp else 0, stamp)

    return sorted(items, key=key, reverse=True)


def area_counts(evidence: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Counter = Counter()
    for item in evidence:
        for area in item.get("areas") or []:
            counts[area] += 1
    return dict(counts)


def leaver_areas(evidence: Sequence[Dict[str, Any]], leaver_name: str, leaver_email: str = "") -> Dict[str, int]:
    counts: Counter = Counter()
    for item in evidence:
        if not is_leaver(item, leaver_name, leaver_email):
            continue
        for area in item.get("areas") or []:
            counts[area] += 1
    return dict(counts)


def ownership(evidence: Sequence[Dict[str, Any]], leaver_name: str, leaver_email: str = "") -> List[Dict[str, Any]]:
    """Per-area commit ownership. Share is the leaver's commits / all commits in the area."""
    commits = by_type(evidence, COMMIT_SOURCES)
    totals: Counter = Counter()
    mine: Counter = Counter()
    collaborators: Dict[str, Counter] = defaultdict(Counter)
    ids: Dict[str, List[str]] = defaultdict(list)
    last_seen: Dict[str, str] = {}

    for item in commits:
        areas = item.get("areas") or ["unclassified"]
        primary = areas[0]
        totals[primary] += 1
        if is_leaver(item, leaver_name, leaver_email):
            mine[primary] += 1
            if item["id"] not in ids[primary]:
                ids[primary].append(item["id"])
            stamp = item.get("occurred_at") or ""
            if stamp > last_seen.get(primary, ""):
                last_seen[primary] = stamp
        else:
            author = item.get("author") or "unknown"
            if author.lower() not in STOPWORD_AUTHORS:
                collaborators[primary][author] += 1

    rows: List[Dict[str, Any]] = []
    for area, total in totals.items():
        count = mine.get(area, 0)
        if count == 0:
            continue
        rows.append(
            {
                "area": area,
                "area_label": taxonomy.label(area),
                "leaver_commits": count,
                "total_commits": total,
                "share": round(count / total, 3) if total else 0.0,
                "collaborators": [name for name, _ in collaborators[area].most_common(3)],
                "evidence_ids": ids[area][:4],
                "last_touched": last_seen.get(area),
            }
        )
    rows.sort(key=lambda row: (row["share"], row["leaver_commits"]), reverse=True)
    return rows


def open_work(evidence: Sequence[Dict[str, Any]], leaver_name: str, leaver_email: str = "") -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for item in evidence:
        source = item.get("source_type")
        meta = item.get("metadata") or {}
        if source == "task":
            status = str(meta.get("status") or "").lower()
            owner = meta.get("owner") or item.get("author") or ""
            if status in OPEN_TASK_STATUSES and names_match(owner, leaver_name):
                items.append(
                    {
                        "kind": "task",
                        "title": item.get("title"),
                        "status": status,
                        "due": meta.get("due"),
                        "area": (item.get("areas") or ["unclassified"])[0],
                        "evidence_id": item["id"],
                        "url": item.get("url"),
                    }
                )
        elif source == "pull_request":
            if str(meta.get("state") or "").lower() == "open" and is_leaver(item, leaver_name, leaver_email):
                items.append(
                    {
                        "kind": "pull request",
                        "title": item.get("title"),
                        "status": "open",
                        "due": None,
                        "area": (item.get("areas") or ["unclassified"])[0],
                        "evidence_id": item["id"],
                        "url": item.get("url"),
                    }
                )
        elif source == "issue":
            if str(meta.get("state") or "").lower() != "open":
                continue
            assignees = meta.get("assignees") or []
            owned = any(names_match(person, leaver_name) for person in assignees) or is_leaver(
                item, leaver_name, leaver_email
            )
            if owned:
                items.append(
                    {
                        "kind": "issue",
                        "title": item.get("title"),
                        "status": "open",
                        "due": None,
                        "area": (item.get("areas") or ["unclassified"])[0],
                        "evidence_id": item["id"],
                        "url": item.get("url"),
                    }
                )
    items.sort(key=lambda row: (row["status"] != "blocked", row["kind"], row["title"] or ""))
    return items[:10]


def top_area_lookup(rows: Sequence[Dict[str, Any]], limit: int = 4) -> List[str]:
    areas = [row["area"] for row in rows if row.get("area")]
    return areas[:limit]


def people(
    evidence: Sequence[Dict[str, Any]],
    leaver_name: str,
    leaver_email: str = "",
    focus_areas: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Who else has context: co-authors in the leaver's areas, plus chat counterparties."""
    focus = set(focus_areas or [])
    groups: Dict[str, Dict[str, Any]] = {}

    for item in evidence:
        author = item.get("author")
        if not author or author.lower() in STOPWORD_AUTHORS:
            continue
        if is_leaver(item, leaver_name, leaver_email):
            continue
        areas = item.get("areas") or []
        overlap = [area for area in areas if area in focus]
        if not overlap:
            continue
        entry = groups.setdefault(
            author,
            {"name": author, "records": 0, "areas": Counter(), "evidence_ids": [], "sources": Counter()},
        )
        entry["records"] += 1
        entry["areas"].update(overlap)
        entry["sources"][item.get("source_type")] += 1
        if len(entry["evidence_ids"]) < 4 and item["id"] not in entry["evidence_ids"]:
            entry["evidence_ids"].append(item["id"])

    rows: List[Dict[str, Any]] = []
    for entry in groups.values():
        top = [area for area, _ in entry["areas"].most_common(2)]
        rows.append(
            {
                "name": entry["name"],
                "records": entry["records"],
                "areas": top,
                "area_labels": [taxonomy.label(area) for area in top],
                "evidence_ids": entry["evidence_ids"],
                "sources": dict(entry["sources"]),
            }
        )
    rows.sort(key=lambda row: (row["records"], len(row["areas"])), reverse=True)
    return rows[:5]


def docs_by_area(evidence: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Counter = Counter()
    for item in by_type(evidence, DOC_SOURCES) + [i for i in evidence if i.get("source_type") == "pull_request"]:
        for area in item.get("areas") or []:
            counts[area] += 1
    return dict(counts)


def coverage_gaps(
    evidence: Sequence[Dict[str, Any]],
    claims: Sequence[Dict[str, Any]],
    leaver_name: str,
    leaver_email: str = "",
) -> List[Dict[str, Any]]:
    """Areas the leaver touched that no handover claim represents. This is the trust feature."""
    area_evidence: Dict[str, List[str]] = defaultdict(list)
    for item in evidence:
        if not is_leaver(item, leaver_name, leaver_email):
            continue
        for area in item.get("areas") or []:
            area_evidence[area].append(item["id"])

    covered: set = set()
    for claim in claims:
        if claim.get("status") == "dropped":
            continue
        if claim.get("section") == "snapshot":
            continue
        covered.update(claim.get("evidence_ids") or [])

    doc_counts = docs_by_area(evidence)
    gaps: List[Dict[str, Any]] = []
    for area, ids in area_evidence.items():
        if len(ids) < 2 or area in ("docs", "unclassified"):
            continue
        if any(evidence_id in covered for evidence_id in ids):
            continue
        has_docs = doc_counts.get(area, 0) > 0
        reason = "%d records in %s are not cited by any claim." % (len(ids), taxonomy.label(area))
        if not has_docs:
            reason += " No documentation in this area either."
        gaps.append(
            {
                "area": area,
                "area_label": taxonomy.label(area),
                "evidence_count": len(ids),
                "reason": reason,
                "evidence_ids": ids[:5],
                "has_docs": has_docs,
            }
        )
    gaps.sort(key=lambda row: (row["has_docs"], row["evidence_count"]), reverse=True)
    return gaps[:8]


def snapshot_stats(
    evidence: Sequence[Dict[str, Any]], leaver_name: str, leaver_email: str = ""
) -> Dict[str, Any]:
    mine = [item for item in evidence if is_leaver(item, leaver_name, leaver_email)]
    commits = by_type(mine, COMMIT_SOURCES)
    pulls = by_type(mine, ("pull_request",))
    reviews = by_type(mine, ("review",))
    tasks = by_type(mine, ("task",))
    chats = by_type(mine, CHAT_SOURCES)
    notes = by_type(mine, DOC_SOURCES)
    dates = sorted([item["occurred_at"] for item in evidence if item.get("occurred_at")])
    area_counter = Counter()
    for item in mine:
        for area in item.get("areas") or []:
            area_counter[area] += 1

    return {
        "commits": len(commits),
        "pull_requests": len(pulls),
        "reviews": len(reviews),
        "tasks": len(tasks),
        "chats": len(chats),
        "notes": len(notes),
        "leaver_records": len(mine),
        "areas": [area for area, _ in area_counter.most_common(6)],
        "area_counts": dict(area_counter),
        "first_seen": dates[0] if dates else None,
        "last_seen": dates[-1] if dates else None,
        "sources": sorted({item.get("source_type") for item in evidence}),
        "total_records": len(evidence),
    }
