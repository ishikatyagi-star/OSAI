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


async def run_ask(
    request: AskRequest,
    requester_permissions: list[str] | None = None,
    requester_tier: str = "red",
) -> AskResponse:
    started = time.monotonic()
    conversation_id = request.conversation_id or str(uuid4())

    # 1. RAG: retrieve + synthesize an answer with citations. Pass the caller's
    #    permissions + clearance tier so retrieval is scoped to their access.
    rag = await retrieve_answer(
        SearchRequest(
            org_id=request.org_id,
            query=request.question,
            requester_permissions=requester_permissions or [],
            requester_tier=requester_tier,
        )
    )

    # 2. Plan actions (proposed, never auto-executed). Planners record the
    #    execution descriptor (provider + payload) into _PROPOSED themselves.
    actions = await _plan_actions(request, rag.answer)

    if settings.llm_api_key:
        model_route = f"llm:{settings.llm_model}"
    elif settings.gemini_api_key:
        model_route = f"gemini:{settings.gemini_model}"
    else:
        model_route = "mock-fallback"
    return AskResponse(
        conversation_id=conversation_id,
        answer=rag.answer,
        citations=rag.citations,
        actions_taken=actions,
        enough_context=rag.enough_context,
        model_route=model_route,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


async def confirm_action(
    action_id: str, conversation_id: str, caller_org_id: str | None = None
) -> ConfirmActionResult:
    proposed = _PROPOSED.get(action_id)
    if proposed is None:
        return ConfirmActionResult(
            id=action_id,
            status="failed",
            message="Action not found or already handled.",
            error="unknown_action",
        )
    # Cross-tenant guard: only the org that proposed the action may execute it.
    # This endpoint drives real connector side-effects (Freshdesk/Slack/Notion),
    # so a mismatch must never fall through to execution.
    if caller_org_id is not None and proposed.get("org_id") != caller_org_id:
        return ConfirmActionResult(
            id=action_id,
            status="failed",
            message="This action does not belong to your workspace.",
            error="org_mismatch",
        )
    if proposed.get("provider") == "composio":
        return await _execute_composio(action_id, proposed)
    try:
        connector = connector_registry.get(proposed["tool"])
        result = await connector.execute_action(
            proposed["org_id"],
            ConnectorAction(action_type=proposed["action"], payload=proposed["payload"]),
        )
        _PROPOSED.pop(action_id, None)
        if result.status == "succeeded":
            _remember_resolution(proposed)
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
    from connectors.composio_tool import get_default_composio_client

    tools = available_action_tools()
    composio = get_default_composio_client()
    if not tools and not composio.available():
        return []
    if settings.gemini_api_key or settings.llm_api_key:
        try:
            return await _llm_plan(request, answer, tools)
        except Exception as exc:  # noqa: BLE001 — degrade to heuristic on any LLM failure
            logger.info("LLM action planning unavailable (%s); using heuristic.", exc)
    return _heuristic_plan(request, answer, tools, composio)


def _record(
    org_id: str,
    provider: str,
    tool: str,
    action_slug: str,
    payload: dict,
    summary: str,
) -> AgentAction:
    """Build a proposed action and stash its execution descriptor for confirm."""
    action = AgentAction(
        id=str(uuid4()),
        tool=tool,
        action=action_slug,
        summary=summary,
        status="proposed",
        requires_confirmation=True,
        params=payload,
    )
    _PROPOSED[action.id] = {
        "org_id": org_id,
        "provider": provider,
        "tool": tool,
        "action": action_slug,
        "payload": payload,
        "summary": summary,
    }
    return action


def _remember_resolution(proposed: dict) -> None:
    """Record how an action was handled so OSAI can reuse it later."""
    try:
        from db.session import SessionLocal
        from memory.org_memory import record_memory

        with SessionLocal() as session:
            record_memory(
                session,
                proposed["org_id"],
                kind="resolution",
                content=f"{proposed.get('summary', 'Action')} — handled via {proposed['tool']}.",
            )
    except Exception as exc:  # noqa: BLE001 — memory is best-effort
        logger.info("Could not record resolution memory: %s", exc)


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
        payload = build_payload(name, item.get("params", {}))
        actions.append(
            _record(
                request.org_id,
                "connector",
                spec["tool"],
                spec["action"],
                payload,
                item.get("summary", spec["description"]),
            )
        )
    return actions


def _heuristic_plan(
    request: AskRequest, answer: str, tools: dict, composio
) -> list[AgentAction]:
    q = request.question.lower()
    summary_src = request.question.strip()

    # Composio: real-time web search (no_auth, executes immediately).
    _web_cues = ("search the web", "web search", "look up online", "search online", "latest news")
    if composio.available() and any(k in q for k in _web_cues):
        return [
            _record(
                request.org_id,
                "composio",
                "composio_search",
                "COMPOSIO_SEARCH_DUCK_DUCK_GO_SEARCH",
                {"query": summary_src[:200]},
                f"Search the web: {summary_src[:80]}",
            )
        ]
    if "create_freshdesk_ticket" in tools and any(
        k in q for k in ("ticket", "raise", "bug", "issue", "support", "complaint")
    ):
        return [
            _record(
                request.org_id,
                "connector",
                "freshdesk",
                "create_ticket",
                build_payload(
                    "create_freshdesk_ticket",
                    {"subject": summary_src[:120], "description": answer[:1000]},
                ),
                f"Open a Freshdesk ticket: {summary_src[:80]}",
            )
        ]
    if "post_slack_message" in tools and any(
        k in q for k in ("slack", "notify", "announce", "message", "tell the team")
    ):
        return [
            _record(
                request.org_id,
                "connector",
                "slack",
                "post_message",
                build_payload(
                    "post_slack_message",
                    {"channel": "general", "text": summary_src[:500]},
                ),
                "Post a Slack message to #general",
            )
        ]
    if "create_notion_page" in tools and any(
        k in q for k in ("notion", "document", "write up", "note", "page", "doc")
    ):
        return [
            _record(
                request.org_id,
                "connector",
                "notion",
                "create_page",
                build_payload(
                    "create_notion_page",
                    {"title": summary_src[:120], "description": answer[:1000]},
                ),
                f"Create a Notion page: {summary_src[:80]}",
            )
        ]
    return []


async def _execute_composio(action_id: str, proposed: dict) -> ConfirmActionResult:
    from connectors.composio_tool import get_default_composio_client

    client = get_default_composio_client()
    try:
        result = await client.execute(
            proposed["action"], proposed["payload"], proposed["org_id"]
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Composio execute %s failed: %s", proposed["action"], exc)
        return ConfirmActionResult(
            id=action_id, status="failed", message="Composio execution error.", error=str(exc)
        )
    _PROPOSED.pop(action_id, None)
    if result.get("successful"):
        _remember_resolution(proposed)
        return ConfirmActionResult(
            id=action_id,
            status="executed",
            message=f"Executed {proposed['action']} via Composio.",
        )
    return ConfirmActionResult(
        id=action_id,
        status="failed",
        message=f"Composio {proposed['action']} did not succeed.",
        error=str(result.get("error")),
    )
