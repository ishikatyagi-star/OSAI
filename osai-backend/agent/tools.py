"""Tool registry for the Ask OSAI agent.

Exposes connector actions as JSON-schema tools the reasoning layer can call.
Each tool maps to a connector `execute_action` destination. Kept deliberately
small; Composio (Phase 2) will register additional tools through the same shape.
"""

from __future__ import annotations

from typing import Any

from connectors.registry import connector_registry

# Action-capable connectors and the action they expose to the agent.
# payload_builder turns planner-supplied params into the connector payload.
_ACTION_TOOLS: dict[str, dict[str, Any]] = {
    "create_freshdesk_ticket": {
        "tool": "freshdesk",
        "action": "create_ticket",
        "description": "Open a Freshdesk support ticket for an issue or request.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Short ticket title."},
                "description": {"type": "string", "description": "Ticket body / details."},
            },
            "required": ["subject"],
        },
    },
    "post_slack_message": {
        "tool": "slack",
        "action": "post_message",
        "description": "Post a message to a Slack channel.",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name, e.g. 'general'."},
                "text": {"type": "string", "description": "Message text."},
            },
            "required": ["text"],
        },
    },
    "create_notion_page": {
        "tool": "notion",
        "action": "create_page",
        "description": "Create a Notion page with a title and body.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["title"],
        },
    },
}


def available_action_tools() -> dict[str, dict[str, Any]]:
    """Action tools whose connector is registered and execute-capable."""
    enabled: dict[str, dict[str, Any]] = {}
    for name, spec in _ACTION_TOOLS.items():
        try:
            connector = connector_registry.get(spec["tool"])
        except KeyError:
            continue
        if "execute" in getattr(connector, "capabilities", set()):
            enabled[name] = spec
    return enabled


def tool_specs(org_id: str) -> list[dict[str, Any]]:
    """JSON-schema tool list for the planner / UI. `search_knowledge` is implicit
    (always run first), so only action tools are advertised here."""
    specs: list[dict[str, Any]] = []
    for name, spec in available_action_tools().items():
        specs.append(
            {
                "name": name,
                "tool": spec["tool"],
                "action": spec["action"],
                "description": spec["description"],
                "parameters": spec["parameters"],
            }
        )
    return specs


def build_payload(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Normalize planner params into a connector `execute_action` payload."""
    params = params or {}
    if tool_name == "create_freshdesk_ticket":
        return {
            "subject": params.get("subject") or params.get("title") or "OSAI ticket",
            "description": params.get("description", ""),
            "priority": 2,
            "status": 2,
        }
    if tool_name == "post_slack_message":
        return {
            "channel": params.get("channel", "general"),
            "text": params.get("text") or params.get("description", ""),
        }
    if tool_name == "create_notion_page":
        return {
            "title": params.get("title") or params.get("subject") or "OSAI note",
            "description": params.get("description", ""),
        }
    return dict(params)
