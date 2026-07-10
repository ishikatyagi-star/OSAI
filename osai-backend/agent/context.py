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
    connections + native registered connectors). Best-effort: never raises,
    returns "" when nothing is known."""
    lines: list[str] = []
    try:
        from connectors.composio_tool import get_default_composio_client

        client = get_default_composio_client()
        if client.available():
            for c in await client.list_connections(org_id):
                status = (c.get("status") or "").upper()
                if status not in ("ACTIVE", "INITIATED", ""):
                    continue
                toolkit = c.get("toolkit") or "unknown"
                account = f" ({c['email']})" if c.get("email") else ""
                lines.append(
                    f"- {toolkit}{account} (via Composio) — its data is synced "
                    f"into OSAI's knowledge base"
                )
    except Exception as exc:  # noqa: BLE001 — context is best-effort
        logger.info("Could not list Composio connections for context: %s", exc)

    try:
        from connectors.registry import connector_registry

        for connector in connector_registry.all():
            caps = ", ".join(sorted(getattr(connector, "capabilities", set()))) or "sync"
            lines.append(f"- {connector.key} (native connector; capabilities: {caps})")
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
        '  "Connect it from Settings → Integrations, then re-run this automation."'
    )
    return f"{facts}\n\n{connectors}" if connectors else facts
