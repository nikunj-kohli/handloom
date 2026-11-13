"""Access limits, opaque ids and small helpers shared by every route."""
from __future__ import annotations

import re
import secrets
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from fastapi import HTTPException, Request

from . import config


class SlidingWindow:
    """Per-key sliding window counter. In-process; good enough for one worker."""

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = max(1, limit)
        self.window = window_seconds
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.time()

    def check(self, key: str) -> Tuple[bool, int]:
        now = time.time()
        with self._lock:
            if now - self._last_sweep > 300:
                self._sweep(now)
                self._last_sweep = now
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry = int(self.window - (now - bucket[0])) + 1
                return False, max(retry, 1)
            bucket.append(now)
            return True, 0

    def _sweep(self, now: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]
        for key in stale:
            del self._hits[key]


GENERAL_LIMIT = SlidingWindow(config.RATE_LIMIT_PER_MINUTE)
HEAVY_LIMIT = SlidingWindow(config.HEAVY_RATE_LIMIT_PER_MINUTE)
GENERATION_SLOTS = threading.BoundedSemaphore(config.MAX_CONCURRENT_GENERATIONS)

_IP_RE = re.compile(r"^[0-9a-fA-F:.]{3,45}$")


def client_key(request: Request) -> str:
    """Best-effort client identity for rate limiting. Never stored."""
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
            if _IP_RE.match(candidate):
                return candidate
    host = request.client.host if request.client else "unknown"
    return host or "unknown"


def enforce_general_limit(request: Request) -> None:
    allowed, retry = GENERAL_LIMIT.check(client_key(request))
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Retry in %ds." % retry)


def enforce_heavy_limit(request: Request) -> None:
    """For endpoints that do real work: ingest, generate, sign, export."""
    key = client_key(request)
    for limiter in (GENERAL_LIMIT, HEAVY_LIMIT):
        allowed, retry = limiter.check(key)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="This action is rate limited to %d per minute. Retry in %ds."
                % (config.HEAVY_RATE_LIMIT_PER_MINUTE, retry),
            )


def new_id(prefix: str, size: int = 9) -> str:
    return "%s-%s" % (prefix, secrets.token_urlsafe(size))


def new_session_id() -> str:
    return "run-" + secrets.token_urlsafe(18)


def new_token() -> str:
    return secrets.token_urlsafe(24)


def clamp_text(value: Optional[str], limit: int) -> str:
    if not value:
        return ""
    text = str(value).replace("\x00", "").strip()
    return text[:limit]


def clean_one_line(value: Optional[str], limit: int = 200) -> str:
    text = clamp_text(value, limit * 4)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def fingerprint(payload: str) -> str:
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
