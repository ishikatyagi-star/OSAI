"""Composio tool-calling agent loop (mocked LLM + Composio).

The whole point of this path is that it has NO per-connector code, so the tests
exercise the generic machinery: read-only tool exposure, schema pruning, the
tool-call loop, and the iteration cap.
"""

from __future__ import annotations

import connectors.composio_agent as agent


class _FakeComposio:
    def __init__(self):
        self.executed: list[tuple[str, dict]] = []

    def available(self):
        return True

    async def list_connections(self, org_id):
        return [{"toolkit": "gmail", "status": "ACTIVE"}]

    async def list_tools(self, toolkits, limit=30):
        return [
            {
                "name": "GMAIL_FETCH_EMAILS",
                "description": "Fetch emails",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer"},
                        "page_token": {"type": "string"},
                        "include_spam_trash": {"type": "boolean"},
                        "label_ids": {"type": "array"},
                    },
                    "required": [],
                },
            },
            # A write tool that must never be exposed to the model.
            {"name": "GMAIL_SEND_EMAIL", "description": "Send", "parameters": {}},
        ]

    async def execute(self, name, args, user_id):
        self.executed.append((name, args))
        return {"successful": True, "data": {"messages": [{"sender": "a@b.com"}]}}


def _script_llm(monkeypatch, turns):
    """Feed chat_with_tools a scripted sequence of assistant messages."""
    calls = {"n": 0}

    async def _fake_chat(messages, tools, model=None):
        i = calls["n"]
        calls["n"] += 1
        _fake_chat.last_tools = tools  # noqa: SLF001 — test introspection
        return turns[min(i, len(turns) - 1)]

    monkeypatch.setattr(agent, "chat_with_tools", _fake_chat)
    monkeypatch.setattr(agent, "tool_calling_available", lambda: True)
    return _fake_chat


async def test_agent_exposes_only_pruned_read_tools(monkeypatch):
    fake = _FakeComposio()
    chat = _script_llm(monkeypatch, [{"content": "done", "tool_calls": []}])
    await agent.run_composio_agent("org-1", "hi", client=fake)

    names = {t["function"]["name"] for t in chat.last_tools}
    assert names == {"GMAIL_FETCH_EMAILS"}  # write tool excluded
    params = chat.last_tools[0]["function"]["parameters"]["properties"]
    # Safe params kept; noisy optionals pruned (they cause provider 400s).
    assert set(params) == {"query", "max_results"}


async def test_agent_runs_tool_then_answers(monkeypatch):
    fake = _FakeComposio()
    _script_llm(
        monkeypatch,
        [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "GMAIL_FETCH_EMAILS",
                            "arguments": '{"max_results": 5}',
                        },
                    }
                ],
            },
            {"content": "You have 1 email from a@b.com.", "tool_calls": []},
        ],
    )
    answer = await agent.run_composio_agent("org-1", "summarize my emails", client=fake)
    assert answer == "You have 1 email from a@b.com."
    assert fake.executed == [("GMAIL_FETCH_EMAILS", {"max_results": 5})]


async def test_agent_ignores_unknown_tool_call(monkeypatch):
    fake = _FakeComposio()
    _script_llm(
        monkeypatch,
        [
            {
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "NOT_A_TOOL", "arguments": "{}"}}
                ],
            },
            {"content": "fallback answer", "tool_calls": []},
        ],
    )
    answer = await agent.run_composio_agent("org-1", "hi", client=fake)
    assert answer == "fallback answer"
    assert fake.executed == []  # unknown tool never executed


async def test_agent_returns_none_without_active_apps(monkeypatch):
    class _NoApps(_FakeComposio):
        async def list_connections(self, org_id):
            return [{"toolkit": "gmail", "status": "EXPIRED"}]

    _script_llm(monkeypatch, [{"content": "x", "tool_calls": []}])
    assert await agent.run_composio_agent("org-1", "hi", client=_NoApps()) is None
