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

from config import settings
from connectors.composio_tool import (
    ComposioClient,
    composio_identity,
    get_default_composio_client,
)

logger = logging.getLogger("osai.composio.live")

# A tool is considered read-only iff its slug contains one of these verbs and
# none of the write verbs. Composio slugs are TOOLKIT_VERB_OBJECT shaped.
_READ_MARKERS = ("_FETCH", "_LIST", "_SEARCH", "_GET", "_FIND")
_WRITE_MARKERS = (
    "_CREATE", "_UPDATE", "_DELETE", "_SEND", "_POST", "_ADD", "_REMOVE",
    "_SET", "_MOVE", "_ARCHIVE", "_UPLOAD", "_WRITE", "_REPLY", "_PATCH",
)
# Read-shaped tools that still aren't a useful source for "read/summarize my X":
# drafts are outbound messages the user is composing, never incoming content, so
# a "summarise my unread emails" question must never fall through to them.
_SKIP_MARKERS = ("_DRAFT",)

# Required parameters we know how to fill without app-specific knowledge.
_QUERY_PARAMS = ("query", "q", "search_query", "keyword", "keywords")
_LIMIT_PARAMS = ("limit", "max_results", "page_size", "per_page", "count")

# Cap the raw tool response we buffer and the snippet we forward as context.
_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_SNIPPET_CHARS = 3500


def _is_read_tool(slug: str) -> bool:
    s = slug.upper()
    return (
        any(m in s for m in _READ_MARKERS)
        and not any(m in s for m in _WRITE_MARKERS)
        and not any(m in s for m in _SKIP_MARKERS)
    )


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


# Extra arguments that make a preferred content tool return rich, summarizable
# data instead of id-only stubs. Merged over the generically-filled arguments
# (these win), then filtered to what the tool actually accepts. Keyed by toolkit
# slug, then tool slug (upper-case). Gmail's fetch defaults to verbose=false,
# which returns message id stubs with no subject/sender/body to summarize.
_PREFERRED_TOOL_ARGS: dict[str, dict[str, dict[str, Any]]] = {
    "gmail": {"GMAIL_FETCH_EMAILS": {"verbose": True, "max_results": 10}},
}

# Natural-language intent -> provider search filter, per toolkit. Lets a plain
# question target the right subset (e.g. "unread emails" -> Gmail is:unread)
# instead of the whole mailbox. Applied only to tools that declare a query param
# and only when the generic filler did not already set one.
_TOOLKIT_QUERY_INTENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "gmail": (
        ("unread", "is:unread"),
        ("important", "is:important"),
        ("starred", "is:starred"),
    ),
}


def _augmented_arguments(
    toolkit: str, spec: dict[str, Any], args: dict[str, Any], question: str
) -> dict[str, Any]:
    """Enrich generically-filled arguments for one tool: add content-richness
    defaults (e.g. Gmail verbose) and a provider search filter derived from the
    question, then keep only parameters the tool declares so a provider can't 400
    on an unknown field."""
    name = (spec.get("name") or "").upper()
    properties = (spec.get("parameters") or {}).get("properties") or {}
    merged = dict(args)
    merged.update(_PREFERRED_TOOL_ARGS.get(toolkit, {}).get(name, {}))
    if "query" in properties and "query" not in merged:
        lowered = question.lower()
        for term, provider_filter in _TOOLKIT_QUERY_INTENTS.get(toolkit, ()):
            if term in lowered:
                merged["query"] = provider_filter
                break
    return {key: value for key, value in merged.items() if key in properties}


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


# The best content-bearing read tool per toolkit, tried first. Without this the
# selector picks whichever read tool Composio lists first — e.g. GMAIL_LIST_DRAFTS
# (usually empty) instead of GMAIL_FETCH_EMAILS — and answers "no data".
_PREFERRED_TOOLS: dict[str, tuple[str, ...]] = {
    "gmail": ("GMAIL_FETCH_EMAILS",),
    "slack": ("SLACK_FETCH_CONVERSATION_HISTORY", "SLACK_LIST_ALL_CHANNELS"),
    "notion": ("NOTION_SEARCH_NOTION_PAGE",),
    "googledrive": ("GOOGLEDRIVE_LIST_FILES", "GOOGLEDRIVE_FIND_FILE"),
}

# Verb preference when no explicit tool is listed: content-fetching over
# metadata-listing over single-object gets.
_VERB_RANK = (("_FETCH", 0), ("_SEARCH", 1), ("_FIND", 1), ("_LIST", 2), ("_GET", 3))


def _tool_priority(slug: str, toolkit: str) -> tuple[int, int]:
    s = slug.upper()
    preferred = _PREFERRED_TOOLS.get(toolkit, ())
    if s in preferred:
        return (0, preferred.index(s))
    for marker, rank in _VERB_RANK:
        if marker in s:
            return (1, rank)
    return (2, 0)


def _has_content(data: object) -> bool:
    """True if the response actually carries usable content, so an empty result
    (e.g. {"drafts": [], "resultSizeEstimate": 0}) is skipped for the next tool."""
    if isinstance(data, dict):
        return any(_has_content(v) for v in data.values())
    if isinstance(data, list):
        return any(_has_content(v) for v in data)
    if isinstance(data, str):
        return bool(data.strip())
    return False  # bare numbers/bools/None are not content


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
    requester_permissions: list[str],
    user_id: str | None = None,
    cloud_egress_allowed: bool = True,
    client: ComposioClient | None = None,
) -> str:
    """Best-effort live read from the first connected app the question names.

    Returns a context block for the reasoning layer, or "" when no connected
    app matches, no safe read tool exists, or anything fails — callers treat
    this as optional enrichment, never a hard dependency.
    """
    # Provider responses do not yet carry a data-tier classification. A caller
    # targeting a cloud-capable model must explicitly withhold them until that
    # provenance exists.
    if not cloud_egress_allowed:
        return ""
    # Access model depends on the connection scope. With ORG-shared connections
    # (per-user off), any member reading them would see another's data, so live
    # reads stay admin-only; members use indexed RAG (enforced per document).
    # With PER-USER connections, the read is scoped to the caller's own account
    # below, so it's safe for any authenticated user — that's the whole point of
    # per-user scoping, so don't gate it behind admin.
    if not settings.composio_per_user_connections:
        is_admin = (
            "org:admin" in requester_permissions or "role:admin" in requester_permissions
        )
        if not is_admin:
            return ""
    elif user_id is None:
        # Per-user mode but no identified caller (system/background): nothing to
        # scope to, so don't read a shared account.
        return ""
    client = client or get_default_composio_client()
    if not client.available():
        return ""
    # Scope reads to the caller (per-user when enabled, else org-level), so a
    # user only ever reaches their own connected accounts.
    identity = composio_identity(org_id, user_id)
    try:
        connections = await client.list_connections(identity)
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
        # Best content tool first (preferred per-toolkit, then FETCH>SEARCH>LIST>GET).
        candidates.sort(key=lambda ca: _tool_priority(ca[0]["name"], toolkit))
        for spec, args in candidates[:4]:
            call_args = _augmented_arguments(toolkit, spec, args, question)
            try:
                res = await client.execute_capped(
                    spec["name"], call_args, identity, _MAX_RESPONSE_BYTES
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Live read %s failed: %s", spec["name"], exc)
                continue
            # Skip a call that succeeded but returned nothing usable (e.g. an
            # empty drafts list) and try the next tool, rather than reporting
            # "no data" when a better tool would have returned real content.
            if not res.get("successful") or not _has_content(res.get("data")):
                continue
            snippet = json.dumps(res["data"], default=str)[:_MAX_SNIPPET_CHARS]
            return (
                f"Live data from {toolkit} (fetched just now via {spec['name']}; "
                f"not from the index):\n{snippet}"
            )
    return ""
