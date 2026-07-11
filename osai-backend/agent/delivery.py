"""Deliver automation run results to where the team actually reads them.

Standing delivery is user-configured when the automation is created/edited
(that's the approval), so posting the digest is not gated per-run. Slack is
the first channel: Composio connection when the org has one, else the native
Slack connector.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("osai.delivery")

_MAX_MESSAGE_CHARS = 3500  # Slack truncates ~4k; leave headroom for the header


def _format_message(name: str, result: str) -> str:
    body = result.strip()
    if len(body) > _MAX_MESSAGE_CHARS:
        body = body[:_MAX_MESSAGE_CHARS] + "\n… (truncated — full result in OSAI)"
    return f":robot_face: *{name}*\n{body}"


async def deliver_result(org_id: str, deliver_to: dict, name: str, result: str) -> dict:
    """Deliver a run result. Returns {"status": "delivered"|"failed"|"skipped", ...}.

    Never raises — a delivery failure must not fail the run itself; the outcome
    is recorded on the automation for the UI to surface."""
    channel_kind = (deliver_to or {}).get("channel")
    target = (deliver_to or {}).get("target", "").strip()
    if channel_kind != "slack" or not target:
        return {"status": "skipped", "error": f"Unsupported delivery target: {deliver_to}"}
    if not result.strip():
        return {"status": "skipped", "error": "Empty result — nothing to deliver."}

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
