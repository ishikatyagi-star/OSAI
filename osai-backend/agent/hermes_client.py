"""Client for an optional Hermes-agent sidecar (spike).

Hermes Agent (github.com/NousResearch/hermes-agent) is a single-operator agent.
To use it in OSAI's multi-tenant product without leaking data across orgs, we run
it as a separate service and call it over HTTP, passing the org explicitly and
keeping isolation enforced here. This client is the OSAI side of that seam; it is
inert unless `OSAI_HERMES_SIDECAR_URL` is set.
"""

from __future__ import annotations

import hashlib
import logging

import httpx

from api.schemas.search import SearchRequest
from config import settings
from memory.retriever import retrieve_answer

logger = logging.getLogger("osai.hermes")


def _correlation_id(org_id: str, user_id: str | None) -> str:
    """Non-reversible tag for log correlation — avoids logging raw tenant/user ids."""
    return hashlib.sha256(f"{org_id}:{user_id or ''}".encode()).hexdigest()[:12]


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
    # Egress policy: the sidecar may call cloud models, so only forward citation
    # material from tiers the org allows out (same policy the retriever applies
    # to its own synthesis; retrieve_answer's answer text is already compliant).
    from llm.policy import cloud_llm_allowed, load_data_routing

    routing = load_data_routing(org_id)
    parts = [res.answer or ""]
    for c in res.citations[:5]:
        if not cloud_llm_allowed(routing, getattr(c, "data_tier", None)):
            continue
        title = getattr(c, "title", None) or getattr(c, "source_tool", "")
        snippet = getattr(c, "snippet", None) or getattr(c, "content_preview", "")
        if title or snippet:
            parts.append(f"- {title}: {snippet}")
    return "\n".join(p for p in parts if p).strip()


def hermes_enabled() -> bool:
    # Outside local, config.py's model_validator already refuses to boot with a
    # sidecar URL but no token — this repeats the check as defense in depth so a
    # future config change can't silently start sending unauthenticated /run calls.
    if not settings.hermes_sidecar_url:
        return False
    if settings.env != "local" and not settings.hermes_sidecar_token:
        return False
    return True


async def run_via_hermes(
    prompt: str,
    org_id: str,
    *,
    user_id: str | None = None,
    permissions: list[str] | None = None,
    history: list | None = None,
    extra_context: str = "",
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

    # Hermes has no system prompt of its own: without the environment preamble
    # it answers as a standalone CLI agent (cron jobs, no connector access).
    from agent.context import environment_preamble

    parts = [await environment_preamble(org_id)]
    if extra_context:
        parts.append(extra_context)

    # Ground Hermes in the user's permitted org context (enforced here in OSAI).
    context = await _permitted_context(prompt, org_id, permissions or [])
    if context:
        parts.append(
            "Context from your organization (only what you are permitted to see):\n"
            f"{context}"
        )
    # Recent conversation, so clarifying answers accumulate across turns.
    if history:
        turns = [
            f"{'User' if getattr(m, 'role', '') == 'user' else 'Assistant'}: "
            f"{getattr(m, 'content', '')}"
            for m in history[-10:]
        ]
        parts.append("Conversation so far:\n" + "\n".join(turns))
    parts.append(f"Task: {prompt}")
    augmented = "\n\n".join(p for p in parts if p)
    payload = {
        "prompt": augmented,
        "org_id": org_id,
        "user_id": user_id,
        "permissions": permissions or [],
    }
    headers = (
        {"X-Sidecar-Token": settings.hermes_sidecar_token}
        if settings.hermes_sidecar_token
        else {}
    )
    correlation = _correlation_id(org_id, user_id)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            return resp.json().get("result")
        logger.warning(
            "Hermes sidecar %s -> %s (correlation=%s)", url, resp.status_code, correlation
        )
    except Exception as exc:  # noqa: BLE001 — never let the sidecar break a run
        logger.warning("Hermes sidecar call failed (correlation=%s): %s", correlation, exc)
    return None
