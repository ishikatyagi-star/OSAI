"""Minimal per-IP rate limiting for abuse-prone unauthenticated endpoints
(org provisioning, email login). In-memory sliding window — sufficient for the
single-instance pilot deploy; swap for a Redis-backed limiter before scaling to
multiple web workers (the counters are per-process)."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status
import redis

from config import settings

_HITS: dict[str, deque[float]] = defaultdict(deque)


def _redis_increment(key: str, window_seconds: int) -> int:
    client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    count = int(client.incr(key))
    if count == 1:
        client.expire(key, window_seconds)
    return count


def rate_limit(max_calls: int, window_seconds: int):
    """FastAPI dependency: allow at most `max_calls` from one IP to one path per
    `window_seconds`, else 429. Keyed by client IP + route path."""

    async def _dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"osai:ratelimit:{request.url.path}:{ip}"
        if settings.env not in {"local", "demo"}:
            try:
                if await asyncio.to_thread(_redis_increment, key, window_seconds) > max_calls:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Too many requests. Please wait a moment and try again.",
                    )
                return
            except HTTPException:
                raise
            except Exception:  # noqa: BLE001 - fallback keeps auth available during Redis recovery
                pass
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
