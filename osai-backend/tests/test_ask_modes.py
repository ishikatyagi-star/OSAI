from __future__ import annotations

import pytest
from pydantic import ValidationError

import agent.orchestrator as orchestrator
from api.schemas.agent import AskRequest, ChatMessage
from api.schemas.search import SearchResponse
from llm import gemini


async def test_take_action_intent_reaches_the_existing_safe_planner(monkeypatch):
    prompts: list[str] = []

    async def capture_prompt(prompt: str):
        prompts.append(prompt)
        return {"actions": []}

    monkeypatch.setattr(gemini, "generate_json", capture_prompt)
    monkeypatch.setattr(orchestrator, "tool_specs", lambda _org_id: {})

    result = await orchestrator._llm_plan(
        AskRequest(org_id="org-1", question="Share the update", intent="action"),
        "Grounded context",
        {},
    )

    assert result == []
    assert "selected Take action" in prompts[0]
    assert "never guess missing targets or destructive details" in prompts[0]


async def test_plain_ask_does_not_claim_explicit_action_intent(monkeypatch):
    prompts: list[str] = []

    async def capture_prompt(prompt: str):
        prompts.append(prompt)
        return {"actions": []}

    monkeypatch.setattr(gemini, "generate_json", capture_prompt)
    monkeypatch.setattr(orchestrator, "tool_specs", lambda _org_id: {})

    await orchestrator._llm_plan(
        AskRequest(org_id="org-1", question="What changed?"),
        "Grounded context",
        {},
    )

    assert "selected Take action" not in prompts[0]


async def test_long_ask_bounds_only_its_retrieval_projection(monkeypatch):
    seen_queries: list[str] = []

    async def capture_retrieval(request):
        seen_queries.append(request.query)
        return SearchResponse(answer="Grounded answer", citations=[], enough_context=True)

    async def no_actions(*_args, **_kwargs):
        return []

    monkeypatch.setattr(orchestrator, "retrieve_answer", capture_retrieval)
    monkeypatch.setattr(orchestrator, "_plan_actions", no_actions)
    monkeypatch.setattr(orchestrator, "hermes_enabled", lambda: False)

    question = "x" * 4_001
    result = await orchestrator.run_ask(
        AskRequest(org_id="org-1", question=question),
        requester_permissions=["docs"],
        requester_tier="normal",
        user_id="user-1",
    )

    assert result.answer == "Grounded answer"
    assert seen_queries == [question[:4_000]]


def test_ask_rejects_blank_questions_and_unbounded_history():
    with pytest.raises(ValidationError):
        AskRequest(org_id="org-1", question="   \n\t")

    with pytest.raises(ValidationError):
        ChatMessage(role="user", content="x" * 4_001)

    with pytest.raises(ValidationError):
        AskRequest(
            org_id="org-1",
            question="What changed?",
            history=[ChatMessage(role="user", content="x") for _ in range(11)],
        )
