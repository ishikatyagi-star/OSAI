"""Ask OSAI orchestrator.

Flow: retrieve knowledge (RAG) -> synthesize answer -> propose connector actions
(requires user confirmation) -> on confirm, execute via the connector registry.

Action planning tries Gemini first and falls back to a keyword heuristic so the
agent stays useful even when LLM generation is unavailable. Proposed actions are
held in a per-process store keyed by action id; the confirm endpoint executes them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from uuid import uuid4

from agent.hermes_client import _correlation_id, hermes_enabled, run_via_hermes
from agent.tools import available_action_tools, build_payload, internal_tools, tool_specs
from api.schemas.agent import AgentAction, AskRequest, AskResponse, ConfirmActionResult
from api.schemas.connector import ConnectorAction
from api.schemas.search import SearchRequest
from config import settings
from connectors.registry import connector_registry
from db.repositories import (
    claim_proposed_action,
    discard_proposed_action,
    load_proposed_action,
    save_proposed_action,
)
from memory.retriever import retrieve_answer

logger = logging.getLogger("osai.agent")

# Per-process fast-path cache of proposed actions awaiting confirmation; also
# persisted to connector_actions (see save/load/discard_proposed_action) so a
# confirm survives a different worker or a restart between propose and confirm.
_PROPOSED: dict[str, dict] = {}


def _forget_proposed(action_id: str) -> None:
    _PROPOSED.pop(action_id, None)
    try:
        discard_proposed_action(action_id)
    except Exception:  # noqa: BLE001 — best-effort
        pass


# "Remember that X" — an explicit instruction to store a fact, which is how a
# user teaches OSAI something that lives in no connected tool. It's an order, not
# a retrieval question, so it's handled before RAG (answering it from context
# would drop the fact on the floor).
_MEMORY_INSTRUCTION = re.compile(
    r"^\s*(?:hey\s+)?(?:sheldon[,:\s]+)?"
    r"(?:please\s+|can\s+you\s+|could\s+you\s+|pls\s+)?"
    r"(?:remember|make\s+a\s+note|take\s+a\s+note|note|keep\s+in\s+mind)"
    r"(?:\s+this)?(?:\s+that\b|\s*[:,-]|\s+)\s*(?P<fact>\S.*)$",
    re.IGNORECASE | re.DOTALL,
)
# …but "do you remember X?" / "what do you recall about X?" ask OSAI to *recall*.
# Those must fall through to normal retrieval, not overwrite memory.
_MEMORY_QUESTION = re.compile(
    r"^\s*(?:do|did|does|what|which|when|where|why|how)\b.*\b(?:remember|recall)\b",
    re.IGNORECASE | re.DOTALL,
)


def _memory_instruction(question: str) -> str | None:
    """Return the fact to store if `question` is an explicit remember-this
    instruction, else None."""
    if _MEMORY_QUESTION.match(question or ""):
        return None
    match = _MEMORY_INSTRUCTION.match(question or "")
    if not match:
        return None
    fact = match.group("fact").strip().rstrip("?").strip()
    return fact or None


def _memory_is_writable(org_id: str) -> bool:
    """Mirror require_writable_org: the shared demo workspace is read-only
    outside local dev, so a demo visitor can't write into org memory."""
    return org_id != settings.default_org_id or settings.env == "local"


def _store_fact(org_id: str, fact: str, user_id: str | None) -> bool:
    from db.session import SessionLocal
    from memory.org_memory import record_memory

    try:
        with SessionLocal() as session:
            record_memory(session, org_id, kind="fact", content=fact, user_id=user_id)
        return True
    except Exception as exc:  # noqa: BLE001 — never 500 a chat turn on a memory write
        logger.warning("Could not record fact for %s: %s", org_id, exc)
        return False


async def run_ask(
    request: AskRequest,
    requester_permissions: list[str] | None = None,
    requester_tier: str = "red",
    user_id: str | None = None,
) -> AskResponse:
    started = time.monotonic()
    conversation_id = request.conversation_id or str(uuid4())

    # 0. "Remember that X" — an explicit instruction to store a fact. This is how
    #    a user teaches OSAI something that exists in no connected tool, so it's
    #    handled before RAG: answering it from retrieved context would discard it.
    if (fact := _memory_instruction(request.question)) is not None:
        if not _memory_is_writable(request.org_id):
            answer = (
                "The demo workspace is read-only, so I can't save that to memory here. "
                "In your own workspace I'd remember it and use it in future answers."
            )
        elif _store_fact(request.org_id, fact, user_id):
            answer = f"Got it — I'll remember that {fact}"
        else:
            answer = "I couldn't save that to memory just now. Please try again."
        return AskResponse(
            conversation_id=conversation_id,
            answer=answer,
            citations=[],
            actions_taken=[],
            enough_context=True,
            model_route="memory",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    # 1. RAG: retrieve context + an in-house answer, scoped to the caller's
    #    permissions + clearance tier. Citations always come from OSAI's
    #    retrieval so the answer stays grounded/attributable.
    rag = await retrieve_answer(
        SearchRequest(
            org_id=request.org_id,
            query=request.question,
            requester_permissions=requester_permissions or [],
            requester_tier=requester_tier,
            requester_user_id=user_id,
            department_id=request.department_id,
        )
    )

    # 2. Reasoning engine. If the per-user Hermes sidecar is configured, run the
    #    answer through it (OSAI injects only permission-scoped context and keeps
    #    the propose/confirm action layer here). Fall back to the in-house answer
    #    on any failure — and log it, since a silent fallback while "on Hermes"
    #    would otherwise be invisible.
    answer = rag.answer
    via: str = "osai"

    # Live read: if the question refers to a connected Composio app, pull fresh
    # data from it right now (read-only tools only) so apps without an ingestion
    # fetcher aren't dead ends — the laptop-agent experience. Bounded and
    # best-effort: a slow/failed live read must not delay Ask.
    live_context = ""
    if hermes_enabled():
        from connectors.composio_live import live_read_context

        try:
            live_context = await asyncio.wait_for(
                live_read_context(request.org_id, request.question), timeout=20
            )
        except Exception:  # noqa: BLE001 — enrichment only
            pass

    # Anti-hallucination gate: hand the question to Hermes only when there is
    # real grounding — retrieved org context OR fresh live data. With neither,
    # Hermes (a general LLM) will confidently fabricate answers to questions
    # like "summarize my unread emails" (inventing senders and counts). In that
    # case keep the honest, grounded RAG response ("No relevant context found…")
    # instead of a made-up one. Fabricated data is worse than an empty result.
    grounded = rag.enough_context or bool(live_context)
    if hermes_enabled() and grounded:
        # Connector/environment awareness is injected inside run_via_hermes
        # (environment_preamble); the plain-RAG fallback below stays untouched —
        # its answers come from retrieval and adding connector context there
        # would require threading it through the retriever.
        hermes_answer = await run_via_hermes(
            request.question,
            request.org_id,
            user_id=user_id,
            permissions=requester_permissions or [],
            history=request.history,
            extra_context=live_context,
        )
        if hermes_answer:
            answer = hermes_answer
            via = "hermes"
        else:
            logger.warning(
                "Hermes is configured but fell back to the in-house agent "
                "(correlation=%s) — check the sidecar.",
                _correlation_id(request.org_id, user_id),
            )

    # 3. Plan actions (proposed, never auto-executed) over the final answer.
    actions = await _plan_actions(request, answer, user_id=user_id)

    if via == "hermes":
        model_route = "hermes"
    elif settings.llm_api_key:
        model_route = f"llm:{settings.llm_model}"
    elif settings.gemini_api_key:
        model_route = f"gemini:{settings.gemini_model}"
    else:
        model_route = "mock-fallback"
    return AskResponse(
        conversation_id=conversation_id,
        answer=answer,
        citations=rag.citations,
        actions_taken=actions,
        # Grounded by retrieved context OR fresh live data; drives the
        # "limited context" banner, which shouldn't show when live data answered.
        enough_context=grounded,
        model_route=model_route,
        latency_ms=int((time.monotonic() - started) * 1000),
        via=via,  # type: ignore[arg-type]
    )


async def confirm_action(
    action_id: str,
    conversation_id: str,
    caller_org_id: str | None = None,
    caller_user_id: str | None = None,
    caller_role: str | None = None,
) -> ConfirmActionResult:
    # Fast path (same process), then durable store (another worker / after a
    # restart between propose and confirm).
    proposed = _PROPOSED.get(action_id) or load_proposed_action(action_id)
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
    # Approver binding: execution is restricted to the user who proposed the
    # action or an org admin — not any member who learns the action ID.
    # caller_user_id is None only for system/demo context (no authenticated
    # user), which keeps webhook- and test-driven confirms working.
    if (
        caller_user_id is not None
        and caller_role != "admin"
        and proposed.get("user_id") not in (None, caller_user_id)
    ):
        return ConfirmActionResult(
            id=action_id,
            status="failed",
            message="Only the requesting user or a workspace admin can approve this action.",
            error="not_approver",
        )

    # Single-consume guard: atomically claim the action before any execution so
    # two concurrent confirms can't both drive the same real side effect (SEC-007).
    # The loser gets "already handled"; a failed execution has still consumed the
    # proposal, so the user re-asks rather than risking a duplicate send.
    if claim_proposed_action(action_id) == "taken":
        _PROPOSED.pop(action_id, None)
        return ConfirmActionResult(
            id=action_id,
            status="failed",
            message="Action not found or already handled.",
            error="already_handled",
        )

    if proposed.get("provider") == "internal":
        return _execute_internal(action_id, proposed)
    if proposed.get("provider") == "composio":
        return await _execute_composio(action_id, proposed)
    try:
        connector = connector_registry.get(proposed["tool"])
        result = await connector.execute_action(
            proposed["org_id"],
            ConnectorAction(action_type=proposed["action"], payload=proposed["payload"]),
        )
        _forget_proposed(action_id)
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


async def _plan_actions(
    request: AskRequest, answer: str, user_id: str | None = None
) -> list[AgentAction]:
    from connectors.composio_tool import get_default_composio_client

    # Internal tools (automations) are always available alongside connector tools.
    tools = {**available_action_tools(), **internal_tools()}
    composio = get_default_composio_client()
    if settings.gemini_api_key or settings.llm_api_key:
        try:
            return await _llm_plan(request, answer, tools, user_id=user_id)
        except Exception as exc:  # noqa: BLE001 — degrade to heuristic on any LLM failure
            logger.info("LLM action planning unavailable (%s); using heuristic.", exc)
    return _heuristic_plan(request, answer, tools, composio, user_id=user_id)


def _record(
    org_id: str,
    provider: str,
    tool: str,
    action_slug: str,
    payload: dict,
    summary: str,
    user_id: str | None = None,
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
    descriptor = {
        "org_id": org_id,
        "provider": provider,
        "tool": tool,
        "action": action_slug,
        "payload": payload,
        "summary": summary,
        "user_id": user_id,
    }
    _PROPOSED[action.id] = descriptor  # fast path within this process
    try:
        save_proposed_action(action.id, descriptor)  # durable across workers/restart
    except Exception:  # noqa: BLE001 — durability is best-effort; in-process still works
        logger.warning("Could not persist proposed action %s", action.id)
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


async def _llm_plan(
    request: AskRequest, answer: str, tools: dict, user_id: str | None = None
) -> list[AgentAction]:
    from llm.gemini import generate_json

    history_block = ""
    if request.history:
        turns = "\n".join(
            f"{m.role}: {m.content}" for m in request.history[-10:]
        )
        history_block = f"Conversation so far:\n{turns}\n\n"
    prompt = (
        "You decide whether the user's request implies an action in an external "
        "tool. Available tools (JSON schemas):\n"
        f"{json.dumps(tool_specs(request.org_id))}\n\n"
        f"{history_block}"
        f"User request: {request.question}\n"
        f"Known answer/context: {answer[:1500]}\n\n"
        "If the request is to set up a recurring task/automation but details are "
        "ambiguous (which sources, what cadence, what output), return NO actions — "
        "the answer should ask the clarifying question instead. Only propose "
        "create_automation when the goal, sources, and cadence are all explicit "
        "in the conversation.\n"
        'Return ONLY JSON: {"actions": [{"name": <tool name>, '
        '"params": {..}, "summary": <one line>}]}. '
        "Return an empty list if no action is warranted."
    )
    data = await generate_json(prompt)
    planned = data.get("actions", []) if isinstance(data, dict) else []
    internal = internal_tools()
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
                "internal" if name in internal else "connector",
                spec["tool"],
                spec["action"],
                payload,
                item.get("summary", spec["description"]),
                user_id=user_id,
            )
        )
    return actions


def _infer_cadence(q: str) -> str | None:
    if any(k in q for k in ("hourly", "every hour", "each hour")):
        return "hourly"
    if any(k in q for k in ("daily", "every day", "each day", "every morning")):
        return "daily"
    if any(k in q for k in ("weekly", "every week", "each week")):
        return "weekly"
    return None


def _heuristic_plan(
    request: AskRequest, answer: str, tools: dict, composio, user_id: str | None = None
) -> list[AgentAction]:
    q = request.question.lower()
    summary_src = request.question.strip()

    # Automation setup: only propose when a cadence is explicit AND there is a
    # concrete task beyond the automation keywords themselves; otherwise return
    # nothing so the answer asks the clarifying question.
    if any(k in q for k in ("automation", "automate", "remind", "recurring", "summary of")):
        cadence = _infer_cadence(q)
        if cadence and len(summary_src.split()) >= 5:
            return [
                _record(
                    request.org_id,
                    "internal",
                    "osai",
                    "create_automation",
                    build_payload(
                        "create_automation",
                        {"name": summary_src[:60], "prompt": summary_src, "cadence": cadence},
                    ),
                    f"Create a {cadence} automation: {summary_src[:80]}",
                    user_id=user_id,
                )
            ]
        return []

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


def _execute_internal(action_id: str, proposed: dict) -> ConfirmActionResult:
    """Execute an internal (OSAI-object) action: create/update an automation."""
    from db.repositories import create_automation, update_automation
    from db.session import SessionLocal

    payload = proposed.get("payload") or {}
    action = proposed.get("action")
    try:
        with SessionLocal() as session:
            if action == "create_automation":
                auto = create_automation(
                    session,
                    org_id=proposed["org_id"],
                    user_id=proposed.get("user_id"),
                    name=payload.get("name") or "OSAI automation",
                    prompt=payload.get("prompt") or "",
                    cadence=payload.get("cadence") or "manual",
                )
                _forget_proposed(action_id)
                _remember_resolution(proposed)
                return ConfirmActionResult(
                    id=action_id,
                    status="executed",
                    message=(
                        f"Automation '{auto.name}' created ({auto.cadence}) — "
                        "see the Automations page."
                    ),
                )
            if action == "update_automation":
                auto = update_automation(
                    session,
                    proposed["org_id"],
                    payload.get("automation_id", ""),
                    name=payload.get("name"),
                    prompt=payload.get("prompt"),
                    cadence=payload.get("cadence"),
                    status=payload.get("status"),
                )
                if auto is None:
                    return ConfirmActionResult(
                        id=action_id,
                        status="failed",
                        message="Automation not found in this workspace.",
                        error="automation_missing",
                    )
                _forget_proposed(action_id)
                _remember_resolution(proposed)
                return ConfirmActionResult(
                    id=action_id,
                    status="executed",
                    message=f"Automation '{auto.name}' updated.",
                )
    except Exception as exc:  # noqa: BLE001
        logger.error("Internal action %s failed: %s", action_id, exc)
        return ConfirmActionResult(
            id=action_id, status="failed", message="Execution error.", error=str(exc)
        )
    return ConfirmActionResult(
        id=action_id,
        status="failed",
        message=f"Unknown internal action {action!r}.",
        error="unknown_internal_action",
    )


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
    _forget_proposed(action_id)
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
