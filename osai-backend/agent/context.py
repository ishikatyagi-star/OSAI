"""Environment context for the agent — what's connected and where results go.

The Hermes sidecar (and any LLM reasoning layer) has no innate knowledge of
OSAI's product surface: without this it answers as a standalone CLI agent and
tells users about cron jobs and Telegram delivery that don't exist. These
helpers describe the real environment — the workspace's connected data sources
and how automations actually run — so answers stay grounded in the product.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("osai.agent")


async def connector_context(org_id: str) -> str:
    """Plain-text summary of the org's connected data sources (Composio
    connections + org-scoped configured native connectors). Best-effort: never raises,
    returns "" when nothing is known."""
    lines: list[str] = []
    seen: set[str] = set()
    try:
        from connectors.composio_tool import get_default_composio_client
        from connectors.toolkit_map import to_native_key

        client = get_default_composio_client()
        if client.available():
            for c in await client.list_connections(org_id):
                status = (c.get("status") or "").upper()
                if status != "ACTIVE":
                    continue
                toolkit = c.get("toolkit") or "unknown"
                key = to_native_key(toolkit)
                seen.add(key)
                lines.append(
                    f"- {key} (connected via Composio; indexed data depends on "
                    "the latest successful sync)"
                )
    except Exception as exc:  # noqa: BLE001 — context is best-effort
        logger.info("Could not list Composio connections for context: %s", exc)

    try:
        from db.repositories import list_integrations
        from db.session import SessionLocal

        with SessionLocal() as session:
            integrations = list_integrations(session, org_id)
        for integration in integrations:
            if integration.get("auth_state") != "connected":
                continue
            key = str(integration.get("key") or "unknown")
            if key in seen:
                continue
            capabilities = integration.get("capabilities") or []
            caps = ", ".join(sorted(str(cap) for cap in capabilities)) or "sync"
            lines.append(f"- {key} (connected native source; capabilities: {caps})")
            seen.add(key)
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not list native connectors for context: %s", exc)

    if not lines:
        return ""
    return (
        "Connected data sources for this workspace:\n"
        + "\n".join(lines)
        + "\nUsers can connect more sources from Settings → Integrations."
    )


async def environment_preamble(org_id: str) -> str:
    """Preamble injected ahead of prompts sent to the reasoning layer so it
    answers as OSAI-in-the-product, not as a standalone CLI agent."""
    connectors = await connector_context(org_id)
    facts = (
        "You are OSAI, an internal AI assistant embedded in a web product.\n"
        "Environment facts (do not contradict these):\n"
        "- You are NOT in a CLI or terminal session. The user talks to you in a web chat.\n"
        "- Automation results are shown on the user's Automations dashboard. Do not\n"
        "  offer cron jobs, Telegram, email, or other delivery channels.\n"
        "- OSAI automations run on a cadence of: manual, hourly, daily, or weekly.\n"
        "- You DO have access to the workspace's connected data sources, listed below.\n"
        "- If the user asks about a data source that is not connected, tell them to\n"
        "  connect it from Settings → Integrations, then re-run — never say you\n"
        "  fundamentally lack connector access.\n"
        "- If the user must connect or grant access to a source, tell them exactly:\n"
        '  "Connect it from Settings → Integrations, then re-run this automation."\n'
        "- You answer in a SINGLE turn. You cannot trigger syncs, scans, or\n"
        "  background jobs, and you cannot 'go check' and come back. Never say\n"
        "  things like 'let me trigger a sync', 'scanning your emails', or\n"
        "  'please wait' — you have no such actions and no later turn.\n"
        "- Any data you can use is already included in the context below. If a\n"
        "  fact (a sender, subject, count, name, date) is not in that context,\n"
        "  you do NOT have it: say so plainly. NEVER invent or example-fill data\n"
        "  (no placeholder names like 'John Doe' or 'example.com'). A truthful\n"
        "  'I don't have that indexed yet' is always better than a made-up answer."
    )
    return f"{facts}\n\n{connectors}" if connectors else facts
