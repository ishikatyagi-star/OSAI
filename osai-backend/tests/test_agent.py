"""Tests for the Ask OSAI agent (P1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent.tools import available_action_tools, tool_specs
from api.main import app

client = TestClient(app)


def test_tool_registry_lists_action_tools():
    specs = tool_specs("demo-org")
    # At least the freshdesk/slack/notion action tools should be registered.
    assert len(specs) >= 1
    for spec in specs:
        assert {"name", "tool", "action", "description", "parameters"} <= spec.keys()
        assert spec["parameters"]["type"] == "object"


def test_ask_returns_contract_shape():
    resp = client.post("/ask", json={"org_id": "demo-org", "question": "What is OSAI?"})
    assert resp.status_code == 200
    body = resp.json()
    # Mirrors osai-web AskResponse.
    for key in ("conversation_id", "answer", "citations", "actions_taken", "enough_context"):
        assert key in body
    assert isinstance(body["citations"], list)
    assert isinstance(body["actions_taken"], list)


def test_action_intent_is_proposed_not_executed():
    # Only assert proposal semantics when an action-capable connector exists.
    if "create_freshdesk_ticket" not in available_action_tools():
        return
    resp = client.post(
        "/ask",
        json={"org_id": "demo-org", "question": "Please raise a support ticket for a broken door"},
    )
    body = resp.json()
    actions = body["actions_taken"]
    if actions:  # heuristic/LLM may propose; if so it must require confirmation
        assert all(a["status"] == "proposed" for a in actions)
        assert all(a["requires_confirmation"] for a in actions)


def test_confirm_unknown_action_fails_gracefully():
    resp = client.post(
        "/ask/actions/does-not-exist/confirm", json={"conversation_id": "x"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error"] == "unknown_action"
