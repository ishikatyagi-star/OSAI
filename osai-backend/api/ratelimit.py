"""Minimal per-IP rate limiting for abuse-prone unauthenticated endpoints
(org provisioning, email login). In-memory sliding window — sufficient for the
single-instance pilot deploy; swap for a Redis-backed limiter before scaling to
multiple web workers (the counters are per-process)."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_HITS: dict[str, deque[float]] = defaultdict(deque)


def rate_limit(max_calls: int, window_seconds: int):
    """FastAPI dependency: allow at most `max_calls` from one IP to one path per
    `window_seconds`, else 429. Keyed by client IP + route path."""

    async def _dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"{request.url.path}:{ip}"
        now = time.monotonic()
        hits = _HITS[key]
        cutoff = now - window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= max_calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please wait a moment and try again.",
            )
        hits.append(now)

    return _dependency
