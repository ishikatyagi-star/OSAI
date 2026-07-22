"""Fail-closed health signal for recurring automation scheduling.

Celery's generic ping proves only that some worker is alive. It does not prove
that beat is running or that the queue used by recurring automations is being
consumed. Beat therefore sends a tiny task through that queue; the task writes
this short-lived Redis key. The API offers recurring cadences only while it is
fresh.
"""

from __future__ import annotations

from datetime import UTC, datetime

from redis import Redis

from config import settings

SCHEDULER_HEARTBEAT_KEY = "osai:scheduler:execute-heartbeat:v1"
SCHEDULER_HEARTBEAT_TTL_SECONDS = 180


def _client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )


def write_scheduler_heartbeat() -> str:
    """Record proof that beat and the automation queue reached a worker."""
    recorded_at = datetime.now(UTC).isoformat()
    client = _client()
    try:
        client.setex(
            SCHEDULER_HEARTBEAT_KEY,
            SCHEDULER_HEARTBEAT_TTL_SECONDS,
            recorded_at,
        )
    finally:
        client.close()
    return recorded_at


def scheduler_available() -> bool:
    """Return true only while the beat-to-queue heartbeat is fresh."""
    client = None
    try:
        client = _client()
        return bool(client.get(SCHEDULER_HEARTBEAT_KEY))
    except Exception:  # noqa: BLE001 - unavailable Redis must fail closed
        return False
    finally:
        if client is not None:
            client.close()
