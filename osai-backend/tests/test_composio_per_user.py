"""Per-user Composio connection identity (Option A).

When composio_per_user_connections is on, every connection/read is scoped to the
individual user, so "my email" is the asker's own inbox and no org member can
reach another's connected account. Off by default => org-level, unchanged.
"""

from __future__ import annotations

from config import settings
from connectors.composio_tool import composio_identity


def test_identity_is_org_level_by_default():
    assert settings.composio_per_user_connections is False
    assert composio_identity("org-1", "user-1") == "org-1"
    assert composio_identity("org-1", None) == "org-1"


def test_identity_is_per_user_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "composio_per_user_connections", True)
    assert composio_identity("org-1", "user-1") == "org-1__user-1"
    # Two different users in the same org get distinct identities => no crossover.
    assert composio_identity("org-1", "user-2") == "org-1__user-2"
    assert composio_identity("org-1", "user-1") != composio_identity("org-1", "user-2")
    # No user (system/background) still falls back to org-level.
    assert composio_identity("org-1", None) == "org-1"


class _FakeClient:
    """Records which Composio identity each call was scoped to."""

    def __init__(self):
        self.identities: list[str] = []

    def available(self):
        return True

    async def list_connections(self, identity):
        self.identities.append(identity)
        return [{"toolkit": "gmail", "status": "ACTIVE"}]

    async def list_tools(self, toolkits, limit=30):
        return [{"name": "GMAIL_FETCH_EMAILS", "parameters": {"type": "object", "properties": {}}}]

    async def execute(self, name, args, identity):
        self.identities.append(identity)
        return {"successful": True, "data": {"messages": [{"sender": "a@b.com"}]}}


async def test_agent_scopes_reads_to_the_asker_when_per_user(monkeypatch):
    monkeypatch.setattr(settings, "composio_per_user_connections", True)

    import connectors.composio_agent as agent

    monkeypatch.setattr(agent, "tool_calling_available", lambda: True)

    turns = [
        {
            "content": None,
            "tool_calls": [
                {"id": "c1", "function": {"name": "GMAIL_FETCH_EMAILS", "arguments": "{}"}}
            ],
        },
        {"content": "You have 1 email from a@b.com.", "tool_calls": []},
    ]
    calls = {"n": 0}

    async def _chat(messages, tools, model=None):
        i = calls["n"]
        calls["n"] += 1
        return turns[min(i, len(turns) - 1)]

    monkeypatch.setattr(agent, "chat_with_tools", _chat)

    fake = _FakeClient()
    answer = await agent.run_composio_agent(
        "org-1", "summarize my emails", user_id="user-1", client=fake
    )
    assert answer == "You have 1 email from a@b.com."
    # Every Composio call was scoped to this user's identity, not the bare org.
    assert fake.identities and all(i == "org-1__user-1" for i in fake.identities)
