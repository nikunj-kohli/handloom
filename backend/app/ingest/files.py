"""Upload parsers: plain text, markdown, task CSV, WhatsApp export, Slack JSON.

Every parser returns evidence items in the shared contract and never trusts input.
Unsupported or oversized input raises IngestError with a message we can show a user.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import config
from ..analysis import taxonomy
from ..security import clamp_text, clean_one_line

MAX_MESSAGES_PER_FILE = 300
MAX_ITEMS_PER_FILE = 80
MAX_BODY_CHARS = 4000


class IngestError(Exception):
    """A user-facing ingestion problem (bad file, too large, unreadable)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def ingest_uploads(files: Sequence[Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    items: List[Dict[str, Any]] = []
    warnings: List[str] = []

    if not files:
        return items, warnings
    if len(files) > config.MAX_UPLOAD_FILES:
        raise IngestError("Too many files: %d (limit %d per run)." % (len(files), config.MAX_UPLOAD_FILES))

    total = 0
    for upload in files:
        filename = getattr(upload, "filename", "") or ""
        if not filename.strip():
            continue
        safe_name = _safe_filename(filename)
        raw = upload.file.read(config.MAX_UPLOAD_BYTES + 1)
        if len(raw) > config.MAX_UPLOAD_BYTES:
            raise IngestError(
                "%s is larger than %s MB. Trim it or split it." % (safe_name, round(config.MAX_UPLOAD_BYTES / 1_000_000, 1))
            )
        total += len(raw)
        if total > config.MAX_TOTAL_UPLOAD_BYTES:
            raise IngestError("Uploads exceed %s MB in total." % round(config.MAX_TOTAL_UPLOAD_BYTES / 1_000_000, 1))

        text = raw.decode("utf-8", "replace").replace("\x00", "")
        if not text.strip():
            warnings.append("%s is empty and was skipped." % safe_name)
            continue

        lowered = safe_name.lower()
        parsed: List[Dict[str, Any]] = []
        try:
            if lowered.endswith(".csv"):
                parsed = _parse_tasks_csv(text, safe_name)
            elif lowered.endswith(".json"):
                parsed = _parse_slack_json(text, safe_name)
                if not parsed:
                    parsed = _parse_generic_text(text, safe_name)
                    warnings.append("%s looked like JSON but had no messages; read it as notes." % safe_name)
            elif _looks_like_whatsapp(text, lowered):
                parsed = _parse_whatsapp(text, safe_name)
            elif lowered.endswith((".txt", ".md", ".markdown", ".log", ".text")):
                parsed = _parse_generic_text(text, safe_name)
            else:
                warnings.append("%s: unsupported file type (use .txt, .md, .csv, .json or a WhatsApp export)." % safe_name)
                continue
        except IngestError:
            raise
        except Exception:
            warnings.append("%s could not be parsed and was skipped." % safe_name)
            continue

        if not parsed:
            warnings.append("%s produced no records." % safe_name)
        items.extend(parsed)

    return items, warnings


def _safe_filename(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[\x00-\x1f]", "", base).strip()
    return (base or "upload")[:120]


def _looks_like_whatsapp(text: str, filename: str) -> bool:
    if "whatsapp" in filename:
        return True
    head = text[:4000]
    hits = len(re.findall(r"^\s*\[?\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4},?\s+\d{1,2}:\d{2}", head, re.MULTILINE))
    return hits >= 3


def _parse_generic_text(text: str, filename: str) -> List[Dict[str, Any]]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    if not chunks:
        chunks = [text.strip()]

    merged: List[str] = []
    buffer = ""
    for chunk in chunks:
        if len(buffer) + len(chunk) + 2 <= 900:
            buffer = (buffer + "\n\n" + chunk).strip() if buffer else chunk
        else:
            if buffer:
                merged.append(buffer)
            buffer = chunk[:MAX_BODY_CHARS]
    if buffer:
        merged.append(buffer)

    if len(merged) > MAX_ITEMS_PER_FILE:
        merged = merged[:MAX_ITEMS_PER_FILE]

    meeting = bool(re.search(r"\b(attendees|minutes|meeting|retro|sync|standup|kickoff)\b", text[:1500], re.IGNORECASE))
    source_type = "meeting_note" if meeting else "document"

    items: List[Dict[str, Any]] = []
    for index, body in enumerate(merged, start=1):
        first_line = body.splitlines()[0].strip("# ").strip()
        title = clean_one_line(first_line, 110) if 8 <= len(first_line) <= 110 else "%s — part %d" % (filename, index)
        items.append(
            {
                "source_type": source_type,
                "source_label": filename,
                "external_id": "%s#%d" % (filename, index),
                "title": title,
                "body": body[:MAX_BODY_CHARS],
                "author": None,
                "occurred_at": None,
                "url": None,
                "areas": taxonomy.infer_areas(body),
                "metadata": {"parser": "text", "part": index},
            }
        )
    return items


WHATSAPP_RE = re.compile(
    r"^\s*\[?(?P<date>\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}),?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[APap]\.?[Mm]\.?)?)\]?\s*(?:-\s*)?"
    r"(?P<author>[^:]{1,60}?):\s*(?P<body>.*)$"
)


def _parse_whatsapp(text: str, filename: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, str]] = []
    for line in text.splitlines():
        match = WHATSAPP_RE.match(line)
        if match:
            messages.append(
                {
                    "date": match.group("date").strip(),
                    "time": match.group("time").strip(),
                    "author": clean_one_line(match.group("author"), 60),
                    "body": match.group("body").strip(),
                }
            )
        elif messages and line.strip():
            messages[-1]["body"] = (messages[-1]["body"] + " " + line.strip())[:1200]

    if not messages:
        raise IngestError("%s did not contain readable WhatsApp messages." % filename)

    items = []
    for index, message in enumerate(messages[:MAX_MESSAGES_PER_FILE], start=1):
        body = message["body"]
        if len(body) < 2:
            continue
        items.append(
            {
                "source_type": "chat",
                "source_label": filename,
                "external_id": "%s#%d" % (filename, index),
                "title": clean_one_line(body, 110),
                "body": body[:MAX_BODY_CHARS],
                "author": message["author"] or None,
                "occurred_at": _parse_chat_datetime(message["date"], message["time"]),
                "url": None,
                "areas": taxonomy.infer_areas(body),
                "metadata": {"parser": "whatsapp", "channel": "WhatsApp export"},
            }
        )
    return items


def _parse_chat_datetime(date_text: str, time_text: str) -> Optional[str]:
    normalised_date = date_text.replace(".", "/").replace("-", "/")
    normalised_time = re.sub(r"\s+", "", time_text.upper().replace(".", ""))
    formats = ["%d/%m/%y", "%d/%m/%Y", "%m/%d/%y", "%m/%d/%Y", "%y/%m/%d"]
    for fmt in formats:
        try:
            parsed_date = datetime.strptime(normalised_date, fmt).date()
            break
        except ValueError:
            continue
    else:
        return None
    for time_fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S%p", "%I:%M%p"):
        try:
            parsed_time = datetime.strptime(normalised_time, time_fmt).time()
            return datetime.combine(parsed_date, parsed_time, tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()


def _parse_slack_json(text: str, filename: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(text)
    except ValueError:
        return []

    users: Dict[str, str] = {}
    channel = filename
    if isinstance(data, dict):
        raw_users = data.get("users")
        if isinstance(raw_users, list):
            for user in raw_users:
                if not isinstance(user, dict):
                    continue
                identifier = str(user.get("id") or "")
                profile = user.get("profile") or {}
                display = (
                    user.get("real_name")
                    or user.get("name")
                    or (profile.get("real_name") if isinstance(profile, dict) else None)
                    or (profile.get("display_name") if isinstance(profile, dict) else None)
                    or identifier
                )
                if identifier:
                    users[identifier] = clean_one_line(str(display), 60)
        messages = data.get("messages")
        channel = str(data.get("channel") or filename)
    else:
        messages = data

    if not isinstance(messages, list):
        return []

    items: List[Dict[str, Any]] = []
    for index, message in enumerate(messages[:MAX_MESSAGES_PER_FILE]):
        if not isinstance(message, dict):
            continue
        if message.get("subtype") in ("channel_join", "channel_leave"):
            continue
        body = clamp_text(str(message.get("text") or ""), MAX_BODY_CHARS)
        if len(body) < 2:
            continue
        author = str(message.get("username") or message.get("user") or "unknown")
        author_name = users.get(author) or clean_one_line(author, 60)
        occurred_at = None
        ts = message.get("ts")
        if ts:
            try:
                occurred_at = datetime.fromtimestamp(float(str(ts).split(".")[0]), tz=timezone.utc).isoformat()
            except (ValueError, OSError, OverflowError):
                occurred_at = None
        items.append(
            {
                "source_type": "chat",
                "source_label": str(message.get("channel") or channel)[:120],
                "external_id": "slack:%s" % (ts or index),
                "title": clean_one_line(body, 110),
                "body": body,
                "author": author_name,
                "occurred_at": occurred_at,
                "url": None,
                "areas": taxonomy.infer_areas(body),
                "metadata": {"parser": "slack", "channel": str(message.get("channel") or channel)[:120]},
            }
        )
    return items


TASK_STATUS_ALIASES = {
    "done": "done",
    "closed": "done",
    "complete": "done",
    "completed": "done",
    "resolved": "done",
    "in progress": "in_progress",
    "in_progress": "in_progress",
    "doing": "in_progress",
    "started": "in_progress",
    "blocked": "blocked",
    "waiting": "waiting",
    "on hold": "waiting",
    "todo": "open",
    "to do": "open",
    "open": "open",
    "not started": "open",
    "backlog": "open",
}


def _parse_tasks_csv(text: str, filename: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestError("%s has no header row; expected task columns." % filename)

    fields = list(reader.fieldnames)
    title_col = _pick(fields, ["title", "task", "name", "summary", "item"])
    status_col = _pick(fields, ["status", "state"])
    owner_col = _pick(fields, ["owner", "assignee", "assigned", "who", "person"])
    area_col = _pick(fields, ["area", "component", "project", "team", "squad"])
    due_col = _pick(fields, ["due", "deadline", "target"])
    id_col = _pick(fields, ["id", "key", "ref", "ticket"])
    notes_col = _pick(fields, ["notes", "description", "detail", "comment"])

    if not title_col:
        raise IngestError("%s needs a title/task/name column." % filename)

    items: List[Dict[str, Any]] = []
    for index, row in enumerate(reader, start=1):
        if index > MAX_ITEMS_PER_FILE:
            break
        title = clean_one_line(row.get(title_col) or "", 160)
        if not title:
            continue
        status_raw = clean_one_line(row.get(status_col) or "", 40) if status_col else ""
        status = TASK_STATUS_ALIASES.get(status_raw.lower(), status_raw.lower() or "unknown")
        owner = clean_one_line(row.get(owner_col) or "", 80) if owner_col else ""
        area = clean_one_line(row.get(area_col) or "", 60) if area_col else ""
        due = clean_one_line(row.get(due_col) or "", 40) if due_col else ""
        notes = clamp_text(row.get(notes_col) or "", 800) if notes_col else ""
        external_id = clean_one_line(row.get(id_col) or "", 40) if id_col else "row-%d" % index

        body_parts = ["Status: %s" % (status or "unknown")]
        if owner:
            body_parts.append("Owner: %s" % owner)
        if area:
            body_parts.append("Area: %s" % area)
        if due:
            body_parts.append("Due: %s" % due)
        body = "; ".join(body_parts) + (".\n" + notes if notes else "")

        items.append(
            {
                "source_type": "task",
                "source_label": filename,
                "external_id": "%s:%s" % (filename, external_id),
                "title": title,
                "body": body[:MAX_BODY_CHARS],
                "author": owner or None,
                "occurred_at": None,
                "url": None,
                "areas": taxonomy.infer_areas("%s %s" % (area, title)),
                "metadata": {
                    "parser": "tasks-csv",
                    "status": status,
                    "owner": owner,
                    "area": area,
                    "due": due,
                },
            }
        )
    if not items:
        raise IngestError("%s had a header but no usable rows." % filename)
    return items


def _pick(fieldnames: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    for name in fieldnames:
        normalised = re.sub(r"[^a-z]", "", (name or "").lower())
        for candidate in candidates:
            if candidate in normalised:
                return name
    return None
