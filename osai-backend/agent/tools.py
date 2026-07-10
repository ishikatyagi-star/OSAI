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


# Internal tools: no connector behind them — they act on OSAI's own objects
# (automations). Executed by the orchestrator's confirm path, provider="internal".
_INTERNAL_TOOLS: dict[str, dict[str, Any]] = {
    "create_automation": {
        "tool": "osai",
        "action": "create_automation",
        "description": (
            "Create a recurring OSAI automation once the user's intent is fully "
            "clear. Ask clarifying questions first if the goal, data sources, or "
            "cadence are ambiguous."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short automation title."},
                "prompt": {
                    "type": "string",
                    "description": (
                        "The finalized, fully-specified instruction composed from "
                        "the conversation — not the user's raw message."
                    ),
                },
                "cadence": {
                    "type": "string",
                    "enum": ["manual", "hourly", "daily", "weekly"],
                },
            },
            "required": ["name", "prompt", "cadence"],
        },
    },
    "update_automation": {
        "tool": "osai",
        "action": "update_automation",
        "description": "Update an existing OSAI automation's name, prompt, cadence, or status.",
        "parameters": {
            "type": "object",
            "properties": {
                "automation_id": {"type": "string"},
                "name": {"type": "string"},
                "prompt": {"type": "string"},
                "cadence": {"type": "string", "enum": ["manual", "hourly", "daily", "weekly"]},
                "status": {"type": "string", "enum": ["draft", "active", "paused"]},
            },
            "required": ["automation_id"],
        },
    },
}


def internal_tools() -> dict[str, dict[str, Any]]:
    return dict(_INTERNAL_TOOLS)


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
    for name, spec in {**available_action_tools(), **_INTERNAL_TOOLS}.items():
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
    if tool_name == "create_automation":
        cadence = params.get("cadence", "manual")
        return {
            "name": params.get("name") or params.get("title") or "OSAI automation",
            "prompt": params.get("prompt") or params.get("description", ""),
            "cadence": cadence if cadence in ("manual", "hourly", "daily", "weekly") else "manual",
        }
    if tool_name == "update_automation":
        allowed = ("automation_id", "name", "prompt", "cadence", "status")
        return {k: v for k, v in params.items() if k in allowed and v is not None}
    return dict(params)
