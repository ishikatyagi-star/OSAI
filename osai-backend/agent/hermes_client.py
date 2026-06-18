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

from config import settings

logger = logging.getLogger("osai.hermes")


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
    payload = {
        "prompt": prompt,
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
