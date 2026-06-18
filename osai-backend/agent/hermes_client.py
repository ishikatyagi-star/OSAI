"""Client for an optional Hermes-agent sidecar (spike).

Hermes Agent (github.com/NousResearch/hermes-agent) is a single-operator agent.
To use it in OSAI's multi-tenant product without leaking data across orgs, we run
it as a separate service and call it over HTTP, passing the org explicitly and
keeping isolation enforced here. This client is the OSAI side of that seam; it is
inert unless `OSAI_HERMES_SIDECAR_URL` is set.
"""

from __future__ import annotations

import logging

import httpx

from api.schemas.search import SearchRequest
from config import settings
from memory.retriever import retrieve_answer

logger = logging.getLogger("osai.hermes")


async def _permitted_context(prompt: str, org_id: str, permissions: list[str]) -> str:
    """Retrieve org context the user is permitted to see, to inject into the
    Hermes prompt. Enforcement stays in OSAI: Hermes only ever receives text this
    user is cleared for (the retriever filters by `requester_permissions`)."""
    try:
        res = await retrieve_answer(
            SearchRequest(org_id=org_id, query=prompt, requester_permissions=permissions)
        )
    except Exception:  # noqa: BLE001 — context is best-effort
        return ""
    parts = [res.answer or ""]
    for c in res.citations[:5]:
        title = getattr(c, "title", None) or getattr(c, "source_tool", "")
        snippet = getattr(c, "snippet", None) or getattr(c, "content_preview", "")
        if title or snippet:
            parts.append(f"- {title}: {snippet}")
    return "\n".join(p for p in parts if p).strip()


def hermes_enabled() -> bool:
    return bool(settings.hermes_sidecar_url)


async def run_via_hermes(
    prompt: str,
    org_id: str,
    *,
    user_id: str | None = None,
    permissions: list[str] | None = None,
    timeout: float = 120.0,
) -> str | None:
    """Run a prompt through the *per-user* Hermes sidecar. Carries org_id +
    user_id + the user's permissions so the sidecar runs in that user's isolated
    HERMES_HOME and OSAI can enforce the user's data-access scope on any retrieval
    Hermes requests back. Returns the answer text, or None if Hermes isn't
    configured or the call fails (caller falls back to the in-house agent)."""
    if not settings.hermes_sidecar_url:
        return None
    url = settings.hermes_sidecar_url.rstrip("/") + "/run"

    # Ground Hermes in the user's permitted org context (enforced here in OSAI).
    context = await _permitted_context(prompt, org_id, permissions or [])
    augmented = (
        f"Context from your organization (only what you are permitted to see):\n"
        f"{context}\n\nTask: {prompt}"
        if context
        else prompt
    )
    payload = {
        "prompt": augmented,
        "org_id": org_id,
        "user_id": user_id,
        "permissions": permissions or [],
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            return resp.json().get("result")
        logger.warning("Hermes sidecar %s -> %s", url, resp.status_code)
    except Exception as exc:  # noqa: BLE001 — never let the sidecar break a run
        logger.warning("Hermes sidecar call failed: %s", exc)
    return None
