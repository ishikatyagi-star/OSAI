"""Teaching OSAI a fact through Ask ("remember that X").

This is how a user stores knowledge that lives in no connected tool — the
capability that replaces the wiki. It must store the fact instead of answering
from retrieval, must not fire on recall *questions*, and must never let the
public demo workspace write into org memory (SEC-003).
"""

from __future__ import annotations

import pytest

from agent import orchestrator
from agent.orchestrator import _memory_instruction, run_ask
from api.schemas.agent import AskRequest


@pytest.mark.parametrize(
    "question, expected",
    [
        ("remember that we bill enterprise annually", "we bill enterprise annually"),
        ("Remember: Yash owns infra", "Yash owns infra"),
        ("please remember that the SLA is 4 hours", "the SLA is 4 hours"),
        ("can you remember that we deploy on Fridays", "we deploy on Fridays"),
        ("Sheldon, remember that Q3 starts in July", "Q3 starts in July"),
        ("note that the office is closed Monday", "the office is closed Monday"),
        ("make a note that Bob left the team", "Bob left the team"),
        ("keep in mind that prod is on Supabase", "prod is on Supabase"),
    ],
)
def test_detects_remember_instructions(question, expected):
    assert _memory_instruction(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        # Recall questions ask OSAI to retrieve, not to store.
        "do you remember who owns the VPC setup?",
        "what do you remember about the roadmap?",
        "did you remember to sync Notion?",
        "how do you recall past decisions?",
        # Ordinary questions must be untouched.
        "who owns the VPC setup?",
        "summarise open SLA escalations",
        "",
    ],
)
def test_ignores_questions_and_non_instructions(question):
    assert _memory_instruction(question) is None


async def test_remember_stores_the_fact_and_skips_rag(monkeypatch):
    stored: list[tuple[str, str, str | None]] = []

    def _fake_store(org_id, fact, user_id):
        stored.append((org_id, fact, user_id))
        return True

    monkeypatch.setattr(orchestrator, "_store_fact", _fake_store)
    # Retrieval must not run for an instruction — it's not a question.
    async def _boom(*a, **k):
        raise AssertionError("RAG should not run for a remember-this instruction")

    monkeypatch.setattr(orchestrator, "retrieve_answer", _boom)

    res = await run_ask(
        AskRequest(org_id="real-org", question="remember that we bill annually"),
        user_id="u1",
    )

    assert stored == [("real-org", "we bill annually", "u1")]
    assert "remember" in res.answer.lower()
    assert res.model_route == "memory"
    assert res.citations == []


async def test_demo_workspace_cannot_write_memory(monkeypatch):
    """The shared demo is read-only: a visitor must not be able to poison the
    demo org's memory through the chat box."""
    monkeypatch.setattr(orchestrator.settings, "env", "production")
    monkeypatch.setattr(orchestrator.settings, "default_org_id", "demo-org")
    called = False

    def _fake_store(*a, **k):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(orchestrator, "_store_fact", _fake_store)

    res = await run_ask(
        AskRequest(org_id="demo-org", question="remember that we bill annually")
    )

    assert called is False
    assert "read-only" in res.answer.lower()


async def test_local_demo_org_can_still_write(monkeypatch):
    """Local dev signs into seeded demo-org users and still needs writes."""
    monkeypatch.setattr(orchestrator.settings, "env", "local")
    monkeypatch.setattr(orchestrator.settings, "default_org_id", "demo-org")
    monkeypatch.setattr(orchestrator, "_store_fact", lambda *a, **k: True)

    res = await run_ask(
        AskRequest(org_id="demo-org", question="remember that we bill annually")
    )
    assert "read-only" not in res.answer.lower()
