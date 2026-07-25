"""Question-time live reads from connected Composio apps (mocked client)."""

from __future__ import annotations

from connectors.composio_live import live_read_context


class _FakeClient:
    def __init__(self, tools=None, connections=None):
        self._tools = tools or []
        self._connections = connections or [{"toolkit": "linear", "status": "ACTIVE"}]
        self.executed: list[tuple[str, dict]] = []

    def available(self):
        return True

    async def list_connections(self, user_id):
        return self._connections

    async def list_tools(self, toolkits, limit=30):
        return self._tools

    async def execute_capped(self, slug, arguments, user_id, max_bytes):
        self.executed.append((slug, arguments))
        return {"successful": True, "data": {"issues": [{"title": "Fix login bug"}]}}


_LIST_TOOL = {
    "name": "LINEAR_LIST_ISSUES",
    "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
}
_WRITE_TOOL = {
    "name": "LINEAR_CREATE_ISSUE",
    "parameters": {"type": "object", "properties": {}, "required": []},
}
_UNFILLABLE_TOOL = {
    "name": "LINEAR_GET_ISSUE",
    "parameters": {
        "type": "object",
        "properties": {"issue_id": {"type": "string"}},
        "required": ["issue_id"],
    },
}


async def test_live_read_executes_matching_read_tool():
    client = _FakeClient(tools=[_WRITE_TOOL, _UNFILLABLE_TOOL, _LIST_TOOL])
    ctx = await live_read_context(
        "org-1",
        "what are the open linear issues?",
        requester_permissions=["org:admin"],
        client=client,
    )
    assert "Fix login bug" in ctx
    assert "LINEAR_LIST_ISSUES" in ctx
    # Only the safe, fillable read tool ran — never the write tool.
    assert [slug for slug, _ in client.executed] == ["LINEAR_LIST_ISSUES"]
    # Result sets are capped via the optional limit param.
    assert client.executed[0][1] == {"limit": 10}


async def test_live_read_skips_unmentioned_and_inactive_apps():
    client = _FakeClient(
        tools=[_LIST_TOOL],
        connections=[
            {"toolkit": "linear", "status": "INITIATED"},
            {"toolkit": "hubspot", "status": "ACTIVE"},
        ],
    )
    # Linear is mentioned but not ACTIVE; hubspot is active but not mentioned.
    ctx = await live_read_context(
        "org-1",
        "what are the open linear issues?",
        requester_permissions=["org:admin"],
        client=client,
    )
    assert ctx == ""
    assert client.executed == []


async def test_live_read_never_runs_write_tools():
    client = _FakeClient(tools=[_WRITE_TOOL])
    ctx = await live_read_context(
        "org-1",
        "create a linear issue for the outage",
        requester_permissions=["org:admin"],
        client=client,
    )
    assert ctx == ""
    assert client.executed == []


async def test_live_read_skips_provider_when_cloud_egress_is_unclassified():
    client = _FakeClient(tools=[_LIST_TOOL])
    ctx = await live_read_context(
        "org-1",
        "what are the open linear issues?",
        requester_permissions=["org:admin"],
        cloud_egress_allowed=False,
        client=client,
    )
    assert ctx == ""
    assert client.executed == []


async def test_synonyms_route_email_query_to_gmail():
    # "emails" must reach Gmail even though the word "gmail" isn't in the
    # question (regression: without synonyms the agent got no data and
    # hallucinated a fake inbox summary).
    from connectors.composio_live import _matched_toolkits

    active = ["gmail", "googlecalendar", "slack"]
    assert _matched_toolkits("summarize my unread emails", active) == ["gmail"]
    assert _matched_toolkits("scan my mails", active) == ["gmail"]
    assert _matched_toolkits("what's on my calendar today", active) == ["googlecalendar"]
    # No connected app referenced -> no live read (no false positives).
    assert _matched_toolkits("who owns the VPC security setup", active) == []


_DRAFTS_TOOL = {
    "name": "GMAIL_LIST_DRAFTS",
    "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
}
_FETCH_TOOL = {
    "name": "GMAIL_FETCH_EMAILS",
    "parameters": {"type": "object", "properties": {"max_results": {"type": "integer"}}},
}


class _GmailClient(_FakeClient):
    def __init__(self):
        super().__init__(
            tools=[_DRAFTS_TOOL, _FETCH_TOOL],
            connections=[{"toolkit": "gmail", "status": "ACTIVE"}],
        )

    async def execute_capped(self, slug, arguments, user_id, max_bytes):
        self.executed.append((slug, arguments))
        if slug == "GMAIL_LIST_DRAFTS":
            return {"successful": True, "data": {"drafts": [], "resultSizeEstimate": 0}}
        return {"successful": True, "data": {"messages": [{"subject": "Real email"}]}}


async def test_gmail_prefers_fetch_and_skips_empty_drafts():
    client = _GmailClient()
    ctx = await live_read_context(
        "org-1",
        "summarize my unread emails",
        requester_permissions=["org:admin"],
        client=client,
    )
    # FETCH_EMAILS is preferred and tried first; real content is returned.
    assert "Real email" in ctx
    assert "GMAIL_FETCH_EMAILS" in ctx
    assert client.executed[0][0] == "GMAIL_FETCH_EMAILS"


_FETCH_TOOL_FULL = {
    "name": "GMAIL_FETCH_EMAILS",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "verbose": {"type": "boolean"},
            "max_results": {"type": "integer"},
        },
    },
}
_LABELS_TOOL = {
    "name": "GMAIL_LIST_LABELS",
    "parameters": {"type": "object", "properties": {"user_id": {"type": "string"}}},
}


class _GmailFullClient(_FakeClient):
    def __init__(self):
        super().__init__(
            tools=[_DRAFTS_TOOL, _LABELS_TOOL, _FETCH_TOOL_FULL],
            connections=[{"toolkit": "gmail", "status": "ACTIVE"}],
        )

    async def execute_capped(self, slug, arguments, user_id, max_bytes):
        self.executed.append((slug, arguments))
        return {"successful": True, "data": {"messages": [{"subject": "Unread thing"}]}}


async def test_gmail_unread_fetch_targets_inbox_and_skips_drafts_and_labels():
    client = _GmailFullClient()
    ctx = await live_read_context(
        "org-1",
        "summarise my unread emails",
        requester_permissions=["org:admin"],
        client=client,
    )
    assert "Unread thing" in ctx
    # Drafts (outbound) and labels (metadata) are never a source for a "read my
    # emails" question, so only GMAIL_FETCH_EMAILS runs.
    assert [slug for slug, _ in client.executed] == ["GMAIL_FETCH_EMAILS"]
    _slug, args = client.executed[0]
    # Targeted at the unread subset with a bounded result set.
    assert args.get("query") == "is:unread"
    assert args.get("max_results") == 8
