"""Deliver automation run results to where the team actually reads them.

Standing delivery is user-configured when the automation is created/edited
(that's the approval), so posting the digest is not gated per-run. Slack is
the first channel: Composio connection when the org has one, else the native
Slack connector.
"""

from __future__ import annotations

import html
import logging

logger = logging.getLogger("osai.delivery")

_MAX_MESSAGE_CHARS = 3500  # Slack truncates ~4k; leave headroom for the header


def _format_message(name: str, result: str) -> str:
    # Slack's mrkdwn treats <...> as links and mentions. Escape it and keep the
    # generated body in a code block so model output cannot ping people or turn
    # an injected URL into an authoritative-looking action link.
    safe_name = html.escape(name.strip(), quote=False)
    body = html.escape(result.strip(), quote=False).replace("```", "'''")
    if len(body) > _MAX_MESSAGE_CHARS:
        body = body[:_MAX_MESSAGE_CHARS] + "\n... (truncated; full result in Sheldon)"
    return (
        f":robot_face: *{safe_name}*\n"
        "_Automated summary. Verify it in Sheldon before acting._\n"
        f"```{body}```"
    )


async def deliver_result(
    org_id: str,
    deliver_to: dict,
    name: str,
    result: str,
    *,
    source_tiers: list[str | None],
) -> dict:
    """Deliver a run result. Returns {"status": "delivered"|"failed"|"skipped", ...}.

    Never raises — a delivery failure must not fail the run itself; the outcome
    is recorded on the automation for the UI to surface."""
    channel_kind = (deliver_to or {}).get("channel")
    target = (deliver_to or {}).get("target", "").strip()
    if channel_kind != "slack" or not target:
        return {"status": "skipped", "error": f"Unsupported delivery target: {deliver_to}"}
    if not result.strip():
        return {"status": "skipped", "error": "Empty result — nothing to deliver."}

    from llm.policy import cloud_llm_allowed, connector_egress_allowed, load_data_routing

    routing = load_data_routing(org_id)
    if not connector_egress_allowed(routing, source_tiers, channel_kind) or any(
        not cloud_llm_allowed(routing, tier) for tier in source_tiers
    ):
        return {
            "status": "skipped",
            "error": "Delivery blocked by data-routing policy; review the result in Sheldon.",
        }

    text = _format_message(name, result)

    # Composio first: per-org OAuth connection, the primary path for real orgs.
    try:
        from connectors.composio_tool import get_default_composio_client

        client = get_default_composio_client()
        if client.available() and await client.connection_identity("slack", org_id):
            res = await client.execute(
                "SLACK_SEND_MESSAGE", {"channel": target, "text": text}, org_id
            )
            if res.get("successful"):
                return {"status": "delivered", "via": "composio", "target": target}
            logger.warning("Composio Slack delivery failed (org=%s): %s", org_id, res.get("error"))
            return {"status": "failed", "via": "composio", "error": str(res.get("error"))[:300]}
    except Exception as exc:  # noqa: BLE001 — fall through to the native connector
        logger.warning("Composio Slack delivery errored (org=%s): %s", org_id, exc)

    # Native Slack connector fallback (server-configured bot token).
    try:
        from api.schemas.connector import ConnectorAction
        from connectors.registry import connector_registry

        connector = connector_registry.get("slack")
        action = ConnectorAction(
            action_type="post_message", payload={"channel": target, "text": text}
        )
        res = await connector.execute_action(org_id, action)
        if res.status == "succeeded":
            return {"status": "delivered", "via": "native", "target": target, "url": res.url}
        return {"status": "failed", "via": "native", "error": res.error or res.status}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Native Slack delivery errored (org=%s): %s", org_id, exc)
        return {"status": "failed", "error": str(exc)[:300]}
