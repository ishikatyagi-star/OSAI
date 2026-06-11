"""Ask OSAI orchestrator.

Flow: retrieve knowledge (RAG) -> synthesize answer -> propose connector actions
(requires user confirmation) -> on confirm, execute via the connector registry.

Action planning tries Gemini first and falls back to a keyword heuristic so the
agent stays useful even when LLM generation is unavailable. Proposed actions are
held in a per-process store keyed by action id; the confirm endpoint executes them.
"""

from __future__ import annotations

import json
import logging
import time
from uuid import uuid4

from agent.tools import available_action_tools, build_payload, tool_specs
from api.schemas.agent import AgentAction, AskRequest, AskResponse, ConfirmActionResult
from api.schemas.connector import ConnectorAction
from api.schemas.search import SearchRequest
from config import settings
from connectors.registry import connector_registry
from memory.retriever import retrieve_answer

logger = logging.getLogger("osai.agent")

# Per-process store of proposed actions awaiting confirmation. MVP: fine for a
# single worker; swap for a DB table (connector_actions) when multi-worker.
_PROPOSED: dict[str, dict] = {}


async def run_ask(request: AskRequest) -> AskResponse:
    started = time.monotonic()
    conversation_id = request.conversation_id or str(uuid4())

    # 1. RAG: retrieve + synthesize an answer with citations.
    rag = await retrieve_answer(
        SearchRequest(org_id=request.org_id, query=request.question)
    )

    # 2. Plan connector actions (proposed, never auto-executed).
    actions = await _plan_actions(request, rag.answer)
    for action in actions:
        _PROPOSED[action.id] = {
            "org_id": request.org_id,
            "tool": action.tool,
            "action": action.action,
            "payload": build_payload(_tool_name(action.tool), action.params or {}),
        }

    model_route = (
        f"gemini:{settings.gemini_model}" if settings.gemini_api_key else "mock-fallback"
    )
    return AskResponse(
        conversation_id=conversation_id,
        answer=rag.answer,
        citations=rag.citations,
        actions_taken=actions,
        enough_context=rag.enough_context,
        model_route=model_route,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


async def confirm_action(action_id: str, conversation_id: str) -> ConfirmActionResult:
    proposed = _PROPOSED.get(action_id)
    if proposed is None:
        return ConfirmActionResult(
            id=action_id,
            status="failed",
            message="Action not found or already handled.",
            error="unknown_action",
        )
    try:
        connector = connector_registry.get(proposed["tool"])
        result = await connector.execute_action(
            proposed["org_id"],
            ConnectorAction(action_type=proposed["action"], payload=proposed["payload"]),
        )
        _PROPOSED.pop(action_id, None)
        if result.status == "succeeded":
            return ConfirmActionResult(
                id=action_id,
                status="executed",
                external_url=result.url,
                message=f"Executed via {proposed['tool']}.",
            )
        return ConfirmActionResult(
            id=action_id,
            status="failed",
            message=f"{proposed['tool']} returned {result.status}.",
            error=result.error,
        )
    except KeyError:
        return ConfirmActionResult(
            id=action_id,
            status="failed",
            message=f"Connector {proposed['tool']!r} not registered.",
            error="connector_missing",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Action %s execution failed: %s", action_id, exc)
        return ConfirmActionResult(
            id=action_id, status="failed", message="Execution error.", error=str(exc)
        )


# ---------------------------------------------------------------------------
# Action planning
# ---------------------------------------------------------------------------


async def _plan_actions(request: AskRequest, answer: str) -> list[AgentAction]:
    tools = available_action_tools()
    if not tools:
        return []
    if settings.gemini_api_key:
        try:
            return await _llm_plan(request, answer, tools)
        except Exception as exc:  # noqa: BLE001 — degrade to heuristic on any LLM failure
            logger.info("LLM action planning unavailable (%s); using heuristic.", exc)
    return _heuristic_plan(request, answer, tools)


async def _llm_plan(request: AskRequest, answer: str, tools: dict) -> list[AgentAction]:
    from llm.gemini import generate_json

    prompt = (
        "You decide whether the user's request implies an action in an external "
        "tool. Available tools (JSON schemas):\n"
        f"{json.dumps(tool_specs(request.org_id))}\n\n"
        f"User request: {request.question}\n"
        f"Known answer/context: {answer[:1500]}\n\n"
        'Return ONLY JSON: {"actions": [{"name": <tool name>, '
        '"params": {..}, "summary": <one line>}]}. '
        "Return an empty list if no action is warranted."
    )
    data = await generate_json(prompt)
    planned = data.get("actions", []) if isinstance(data, dict) else []
    actions: list[AgentAction] = []
    for item in planned:
        name = item.get("name")
        if name not in tools:
            continue
        spec = tools[name]
        actions.append(
            AgentAction(
                id=str(uuid4()),
                tool=spec["tool"],
                action=spec["action"],
                summary=item.get("summary", spec["description"]),
                status="proposed",
                requires_confirmation=True,
                params=item.get("params", {}),
            )
        )
    return actions


def _heuristic_plan(request: AskRequest, answer: str, tools: dict) -> list[AgentAction]:
    q = request.question.lower()
    summary_src = request.question.strip()

    def make(name: str, params: dict, summary: str) -> list[AgentAction]:
        spec = tools[name]
        return [
            AgentAction(
                id=str(uuid4()),
                tool=spec["tool"],
                action=spec["action"],
                summary=summary,
                status="proposed",
                requires_confirmation=True,
                params=params,
            )
        ]

    if "create_freshdesk_ticket" in tools and any(
        k in q for k in ("ticket", "raise", "bug", "issue", "support", "complaint")
    ):
        return make(
            "create_freshdesk_ticket",
            {"subject": summary_src[:120], "description": answer[:1000]},
            f"Open a Freshdesk ticket: {summary_src[:80]}",
        )
    if "post_slack_message" in tools and any(
        k in q for k in ("slack", "notify", "announce", "message", "tell the team")
    ):
        return make(
            "post_slack_message",
            {"channel": "general", "text": summary_src[:500]},
            "Post a Slack message to #general",
        )
    if "create_notion_page" in tools and any(
        k in q for k in ("notion", "document", "write up", "note", "page", "doc")
    ):
        return make(
            "create_notion_page",
            {"title": summary_src[:120], "description": answer[:1000]},
            f"Create a Notion page: {summary_src[:80]}",
        )
    return []


def _tool_name(tool: str) -> str:
    mapping = {
        "freshdesk": "create_freshdesk_ticket",
        "slack": "post_slack_message",
        "notion": "create_notion_page",
    }
    return mapping.get(tool, tool)
