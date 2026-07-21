"""When the Hermes sidecar is configured, /ask routes the answer through it and
reports via="hermes"; on failure it falls back to the in-house agent (via="osai").
Citations always come from OSAI's retrieval, and the propose/confirm action layer
stays in OSAI."""

from __future__ import annotations

import agent.orchestrator as orch
from api.schemas.agent import AskRequest
from api.schemas.search import SearchResponse, SourceCitation


def _stub_retrieval(monkeypatch):
    async def _fake_retrieve(_request):
        return SearchResponse(
            answer="in-house answer",
            citations=[SourceCitation(source_tool="notion", source_record_title="Doc A")],
            enough_context=True,
        )

    monkeypatch.setattr(orch, "retrieve_answer", _fake_retrieve)

    async def _no_actions(_request, _answer, user_id=None):
        return []

    monkeypatch.setattr(orch, "_plan_actions", _no_actions)


async def test_ask_uses_hermes_when_it_answers(monkeypatch):
    _stub_retrieval(monkeypatch)
    monkeypatch.setattr(orch, "hermes_enabled", lambda: True)

    async def _fake_hermes(
        prompt, org_id, *, user_id=None, permissions=None, history=None, extra_context=""
    ):
        return "hermes answer"

    monkeypatch.setattr(orch, "run_via_hermes", _fake_hermes)

    resp = await orch.run_ask(AskRequest(org_id="o1", question="hi"), user_id="u1")
    assert resp.via == "hermes"
    assert resp.answer == "hermes answer"
    assert resp.model_route == "hermes"
    # Citations still come from OSAI retrieval, not Hermes.
    assert resp.citations and resp.citations[0].source_record_title == "Doc A"


async def test_ask_falls_back_to_inhouse_when_hermes_fails(monkeypatch):
    _stub_retrieval(monkeypatch)
    monkeypatch.setattr(orch, "hermes_enabled", lambda: True)

    async def _fake_hermes(
        prompt, org_id, *, user_id=None, permissions=None, history=None, extra_context=""
    ):
        return None  # sidecar down / errored

    monkeypatch.setattr(orch, "run_via_hermes", _fake_hermes)

    resp = await orch.run_ask(AskRequest(org_id="o1", question="hi"), user_id="u1")
    assert resp.via == "osai"
    assert resp.answer == "in-house answer"


async def test_ask_stays_inhouse_when_hermes_disabled(monkeypatch):
    _stub_retrieval(monkeypatch)
    monkeypatch.setattr(orch, "hermes_enabled", lambda: False)

    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("run_via_hermes should not be called when Hermes is disabled")

    monkeypatch.setattr(orch, "run_via_hermes", _should_not_be_called)

    resp = await orch.run_ask(AskRequest(org_id="o1", question="hi"))
    assert resp.via == "osai"
    assert resp.answer == "in-house answer"


async def test_ungrounded_question_does_not_reach_hermes(monkeypatch):
    """No retrieved context and no live data => Hermes must not be invoked, so it
    can't fabricate. The honest 'no context' answer stands (anti-hallucination)."""

    async def _empty_retrieve(_request):
        return SearchResponse(
            answer="No relevant context found. Trigger a connector sync to ingest data.",
            citations=[],
            enough_context=False,
        )

    monkeypatch.setattr(orch, "retrieve_answer", _empty_retrieve)

    async def _no_actions(_request, _answer, user_id=None):
        return []

    monkeypatch.setattr(orch, "_plan_actions", _no_actions)
    monkeypatch.setattr(orch, "hermes_enabled", lambda: True)

    called = {"hermes": False}

    async def _fake_hermes(*a, **k):
        called["hermes"] = True
        return "FABRICATED: you have 10 unread emails from John Doe"

    monkeypatch.setattr(orch, "run_via_hermes", _fake_hermes)

    resp = await orch.run_ask(
        AskRequest(org_id="o1", question="summarize my unread emails"), user_id="u1"
    )
    assert called["hermes"] is False, "Hermes must not run without grounding"
    assert "No relevant context" in resp.answer
    assert resp.via == "osai"
    assert resp.enough_context is False
