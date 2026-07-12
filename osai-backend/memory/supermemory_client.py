"""Supermemory (supermemory.ai) as OSAI's evolving-memory backbone.

Env-gated: without OSAI_SUPERMEMORY_API_KEY every call is a cheap no-op and
callers fall back to the Postgres org-memory (memory/org_memory.py), so local
dev and tests need no key. With a key, org-shared memories live under the
container tag "org:<org_id>" and personal ones under "user:<user_id>" — the
same audience split as the visibility-grant model.

Sovereignty: only NORMAL-tier content may be sent to the Supermemory cloud.
Amber/red content requires a self-hosted deployment (OSAI_SUPERMEMORY_URL
pointing off-cloud); the client refuses cloud writes above the allowed tier
rather than silently leaking.
"""

from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger("osai.supermemory")

_CLOUD_URL = "https://api.supermemory.ai"
_TIMEOUT = 6.0


def enabled() -> bool:
    return bool(getattr(settings, "supermemory_api_key", None))


def _base_url() -> str:
    return (getattr(settings, "supermemory_url", None) or _CLOUD_URL).rstrip("/")


def _is_cloud() -> bool:
    return _base_url() == _CLOUD_URL


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.supermemory_api_key}"}


def _container_tag(org_id: str, user_id: str | None) -> str:
    return f"user:{user_id}" if user_id else f"org:{org_id}"


def add_memory(
    org_id: str,
    content: str,
    *,
    user_id: str | None = None,
    kind: str = "fact",
    data_tier: str = "normal",
    metadata: dict | None = None,
) -> bool:
    """Store one memory. Returns True when durably accepted by Supermemory.

    False (disabled, tier-blocked, or network failure) tells the caller to use
    the Postgres fallback — never raise into the answer path."""
    if not enabled():
        return False
    if data_tier != "normal" and _is_cloud():
        logger.info(
            "supermemory: refusing cloud write for %s-tier content (org=%s); "
            "self-host required",
            data_tier,
            org_id,
        )
        return False
    try:
        resp = httpx.post(
            f"{_base_url()}/v3/documents",
            headers=_headers(),
            json={
                "content": content,
                "containerTag": _container_tag(org_id, user_id),
                "metadata": {"kind": kind, "org_id": org_id, **(metadata or {})},
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — memory must never break answering
        logger.warning("supermemory add failed (org=%s): %s", org_id, exc)
        return False


def search_memories(
    org_id: str,
    query: str,
    *,
    requester_user_id: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Relevant memories for a query: org-shared plus the requester's personal
    pool (same audience stance as Postgres org-memory). Returns [] on any
    failure so the caller can fall back."""
    if not enabled():
        return []
    tags = [f"org:{org_id}"]
    if requester_user_id:
        tags.append(f"user:{requester_user_id}")
    results: list[dict] = []
    try:
        for tag in tags:
            resp = httpx.post(
                f"{_base_url()}/v4/search",
                headers=_headers(),
                # "hybrid" is required: the default and "memories" modes only
                # return distilled memories (slow async extraction) and yield
                # nothing for freshly-stored facts — verified against the live
                # API. Hybrid searches chunks, so our short facts recall at once.
                json={
                    "q": query,
                    "containerTag": tag,
                    "limit": limit,
                    "searchMode": "hybrid",
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            for r in resp.json().get("results", []):
                # Live shape: chunk content in "chunk", score in "similarity"
                # (memory-mode results use "memory" instead — support both).
                results.append(
                    {
                        "kind": (r.get("metadata") or {}).get("kind", "fact"),
                        "content": r.get("chunk") or r.get("memory") or "",
                        "score": r.get("similarity", r.get("score", 0.0)),
                        "source": "supermemory",
                    }
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("supermemory search failed (org=%s): %s", org_id, exc)
        return []
    results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    return results[:limit]
