"""Answer questions by letting the LLM call an org's connected Composio tools
directly, via function-calling.

This is the scalable alternative to per-connector code. There is NO app-specific
logic here: tool selection, argument-filling, and result interpretation are all
the model's job, driven by the JSON schemas Composio already provides for every
tool. The same loop serves connector #1 and connector #1,000 — adding an app is
"the user connects it", not "we write a fetcher".

Safety: only *read-only* tools are exposed to the model, so this path can never
cause a side effect. Writes stay in OSAI's propose/approve action flow. Every
call is scoped to the org (Composio user_id = org_id).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from connectors.composio_live import _is_read_tool
from connectors.composio_tool import ComposioClient, get_default_composio_client
from llm.gemini import chat_with_tools, tool_calling_available

logger = logging.getLogger("osai.composio.agent")


def _report(context: str, exc: Exception) -> None:
    """Surface an otherwise-swallowed agent failure. When the agent silently
    returns None, Ask falls back to the weaker heuristic and it's invisible why —
    so log it and, when Sentry is configured, capture it so the reason is seen."""
    logger.warning("composio agent: %s: %s", context, exc)
    from config import settings

    if settings.sentry_dsn:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("subsystem", "composio-agent")
            scope.set_context("composio_agent", {"stage": context})
            sentry_sdk.capture_exception(exc)

# Bounds. Tool count keeps the request under provider size limits (the Groq 413);
# iterations bound cost/latency; response bytes bound context growth per call.
_MAX_TOOLS = 40
_MAX_ITERS = 4
_MAX_TOOL_RESULT_CHARS = 4000
# OpenAI function names must match ^[A-Za-z0-9_-]{1,64}$; Composio slugs almost
# always do, but guard so one odd slug can't fail the whole request.
_VALID_NAME_LEN = 64

# Optional params worth keeping because they're simple, useful, and low-risk for
# the model to type correctly. Everything else optional is pruned: providers like
# Groq strictly validate generated arguments against the schema, and models
# routinely mis-type noisy optionals (null page tokens, booleans-as-strings,
# arrays-as-strings), which 400s the whole call. Required params are always kept.
_SAFE_OPTIONAL_PARAMS = {
    "query", "q", "search", "search_query", "keyword", "keywords",
    "max_results", "limit", "page_size", "count", "max", "top_k",
}


def _prune_schema(params: dict[str, Any]) -> dict[str, Any]:
    """Reduce a tool's JSON schema to required params + a safe allowlist, so the
    model has fewer fields to mis-type. Generalizes across all connectors — no
    app-specific rules."""
    if not isinstance(params, dict):
        return {"type": "object", "properties": {}}
    props = params.get("properties") or {}
    required = [r for r in (params.get("required") or []) if r in props]
    kept = {
        name: spec
        for name, spec in props.items()
        if name in required or name in _SAFE_OPTIONAL_PARAMS
    }
    return {"type": "object", "properties": kept, "required": required}


_SYSTEM = (
    "You are OSAI, an assistant embedded in a web product. Answer the user's "
    "question using ONLY the connected-app tools provided. Call the tools you "
    "need, then answer from their results. Rules: never invent data (senders, "
    "counts, names, dates) — if the tools return nothing relevant, say you "
    "couldn't find it. Do not describe steps you're about to take or ask the "
    "user to wait; just call the tools and answer in the end."
)


def _openai_tools(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Composio read-tool specs -> OpenAI function-calling tool definitions."""
    out: list[dict[str, Any]] = []
    for spec in specs:
        name = spec.get("name", "")
        if not name or len(name) > _VALID_NAME_LEN or not _is_read_tool(name):
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": (spec.get("description") or name)[:1000],
                    "parameters": _prune_schema(spec.get("parameters") or {}),
                },
            }
        )
        if len(out) >= _MAX_TOOLS:
            break
    return out


async def _collect_read_tools(
    client: ComposioClient, toolkits: list[str]
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for toolkit in toolkits:
        try:
            specs = await client.list_tools([toolkit], limit=30)
        except Exception:  # noqa: BLE001 — skip an app whose tools won't load
            continue
        tools.extend(_openai_tools(specs))
        if len(tools) >= _MAX_TOOLS:
            break
    return tools[:_MAX_TOOLS]


async def run_composio_agent(
    org_id: str,
    question: str,
    *,
    client: ComposioClient | None = None,
    history: list | None = None,
) -> str | None:
    """Let the model call the org's connected read tools to answer `question`.

    Returns the grounded answer, or None when tool-calling isn't configured,
    the org has no connected apps, or the loop produced nothing — callers treat
    None as "fall through to the normal path".
    """
    client = client or get_default_composio_client()
    if not (tool_calling_available() and client.available()):
        return None
    try:
        connections = await client.list_connections(org_id)
    except Exception as exc:  # noqa: BLE001
        _report("list_connections failed", exc)
        return None
    active = [
        c["toolkit"]
        for c in connections
        if c.get("toolkit") and (c.get("status") or "").upper() == "ACTIVE"
    ]
    if not active:
        return None

    tools = await _collect_read_tools(client, active)
    if not tools:
        return None
    tool_names = {t["function"]["name"] for t in tools}

    messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM}]
    for m in (history or [])[-6:]:
        role = "user" if getattr(m, "role", "") == "user" else "assistant"
        messages.append({"role": role, "content": getattr(m, "content", "")})
    messages.append({"role": "user", "content": question})

    for _ in range(_MAX_ITERS):
        try:
            msg = await chat_with_tools(messages, tools)
        except Exception as exc:  # noqa: BLE001 — best-effort; fall through
            _report("chat_with_tools failed", exc)
            return None

        calls = msg.get("tool_calls") or []
        if not calls:
            answer = (msg.get("content") or "").strip()
            return answer or None

        # Record the assistant turn (with its tool_calls) before the results.
        messages.append(msg)
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (ValueError, TypeError):
                args = {}
            if name not in tool_names:
                content = json.dumps({"error": f"unknown tool {name}"})
            else:
                try:
                    res = await client.execute(name, args, org_id)
                    content = json.dumps(res.get("data"), default=str)[
                        :_MAX_TOOL_RESULT_CHARS
                    ]
                except Exception as exc:  # noqa: BLE001 — report to the model, keep going
                    content = json.dumps({"error": str(exc)[:200]})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": content,
                }
            )

    # Ran out of iterations without a final text answer.
    return None
