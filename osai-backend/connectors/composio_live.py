"""Live question-time reads from connected Composio apps.

Indexed sync (composio_ingest) covers apps with a curated fetcher; every other
connected app would otherwise be a dead end at question time. This module gives
Ask a laptop-agent-style live path: when the question names a connected app,
execute one of that app's *read-only* tools right now and hand the raw result to
the reasoning layer as context. Nothing is stored — freshness over recall.

Safety model: only tools whose slug reads as a read operation are considered,
and only ones whose required parameters we can fill generically (a search query
or a result limit). Anything else is skipped — writes always go through the
propose/approve action flow, never through this path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from connectors.composio_tool import ComposioClient, get_default_composio_client

logger = logging.getLogger("osai.composio.live")

# A tool is considered read-only iff its slug contains one of these verbs and
# none of the write verbs. Composio slugs are TOOLKIT_VERB_OBJECT shaped.
_READ_MARKERS = ("_FETCH", "_LIST", "_SEARCH", "_GET", "_FIND")
_WRITE_MARKERS = (
    "_CREATE", "_UPDATE", "_DELETE", "_SEND", "_POST", "_ADD", "_REMOVE",
    "_SET", "_MOVE", "_ARCHIVE", "_UPLOAD", "_WRITE", "_REPLY", "_PATCH",
)

# Required parameters we know how to fill without app-specific knowledge.
_QUERY_PARAMS = ("query", "q", "search_query", "keyword", "keywords")
_LIMIT_PARAMS = ("limit", "max_results", "page_size", "per_page", "count")

# Cap the raw tool response we buffer and the snippet we forward as context.
_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_SNIPPET_CHARS = 3500


def _is_read_tool(slug: str) -> bool:
    s = slug.upper()
    return any(m in s for m in _READ_MARKERS) and not any(m in s for m in _WRITE_MARKERS)


def _fillable_arguments(spec: dict[str, Any], question: str) -> dict[str, Any] | None:
    """Arguments for a tool call, or None if a required param can't be filled."""
    params = spec.get("parameters") or {}
    required = params.get("required") or []
    properties = params.get("properties") or {}
    args: dict[str, Any] = {}
    for name in required:
        if name in _QUERY_PARAMS:
            args[name] = question
        elif name in _LIMIT_PARAMS:
            args[name] = 10
        else:
            return None
    # Keep unrequested result sets small when the tool supports a limit.
    for name in _LIMIT_PARAMS:
        if name in properties and name not in args:
            args[name] = 10
            break
    return args


# Natural-language terms that should trigger a live read of a connected app,
# beyond the app's own name. Without these, "summarize my unread emails" never
# reaches Gmail (the word "gmail" isn't in the question) and the agent answers
# with no data. Keyed by Composio toolkit slug.
_TOOLKIT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "gmail": ("email", "emails", "e-mail", "mail", "mails", "inbox", "unread"),
    "googlecalendar": ("calendar", "meeting", "meetings", "schedule", "event", "events"),
    "googledrive": ("drive", "document", "documents", "docs", "file", "files", "spreadsheet"),
    "slack": ("slack", "message", "messages", "channel", "channels", "dm", "thread"),
    "notion": ("notion", "wiki", "page", "pages"),
    "github": ("github", "repo", "repos", "repository", "pull request", "commit", "issue"),
    "linear": ("linear", "ticket", "tickets"),
}


def _matched_toolkits(question: str, toolkits: list[str]) -> list[str]:
    """Connected toolkits the question plausibly refers to — by app name or a
    common synonym (so "my emails" reaches Gmail, "my calendar" reaches Google
    Calendar, etc.). Only connected apps are considered, so synonyms can't pull
    in something the org hasn't authorized."""
    q = f" {question.lower()} "
    matched = []
    for slug in toolkits:
        name = (slug or "").lower()
        terms = (name, name.replace("_", " ")) + _TOOLKIT_SYNONYMS.get(name, ())
        if any(t and (t in q) for t in terms):
            matched.append(slug)
    return matched


async def live_read_context(
    org_id: str,
    question: str,
    *,
    client: ComposioClient | None = None,
) -> str:
    """Best-effort live read from the first connected app the question names.

    Returns a context block for the reasoning layer, or "" when no connected
    app matches, no safe read tool exists, or anything fails — callers treat
    this as optional enrichment, never a hard dependency.
    """
    client = client or get_default_composio_client()
    if not client.available():
        return ""
    try:
        connections = await client.list_connections(org_id)
    except Exception:  # noqa: BLE001 — live reads are best-effort
        return ""
    active = [
        c.get("toolkit")
        for c in connections
        if c.get("toolkit") and (c.get("status") or "").upper() == "ACTIVE"
    ]
    for toolkit in _matched_toolkits(question, active):
        try:
            specs = await client.list_tools([toolkit], limit=30)
        except Exception:  # noqa: BLE001
            continue
        candidates = [
            (spec, args)
            for spec in specs
            if _is_read_tool(spec.get("name", ""))
            and (args := _fillable_arguments(spec, question)) is not None
        ]
        # Prefer bulk reads (FETCH/LIST/SEARCH) over single-object GETs.
        candidates.sort(
            key=lambda ca: 0 if any(
                m in ca[0]["name"].upper() for m in ("_FETCH", "_LIST", "_SEARCH")
            ) else 1
        )
        for spec, args in candidates[:3]:
            try:
                res = await client.execute_capped(
                    spec["name"], args, org_id, _MAX_RESPONSE_BYTES
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Live read %s failed: %s", spec["name"], exc)
                continue
            if not res.get("successful") or res.get("data") is None:
                continue
            snippet = json.dumps(res["data"], default=str)[:_MAX_SNIPPET_CHARS]
            return (
                f"Live data from {toolkit} (fetched just now via {spec['name']}; "
                f"not from the index):\n{snippet}"
            )
    return ""
