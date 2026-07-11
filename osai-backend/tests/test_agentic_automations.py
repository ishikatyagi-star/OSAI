"""Agentic automations: connector-aware context, conversational creation via the
propose→confirm loop, PATCH editing, and run-time "what's new" context."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

import agent.hermes_client as hermes_mod
import agent.orchestrator as orch
from agent.context import connector_context, environment_preamble
from api.main import app
from api.schemas.agent import AskRequest
from db.repositories import list_automations, list_documents_since
from db.session import SessionLocal

client = TestClient(app)


# --- Phase 1: connector context + environment preamble ----------------------


async def test_connector_context_empty_when_nothing_available(monkeypatch):
    from connectors import composio_tool, registry

    monkeypatch.setattr(
        composio_tool.get_default_composio_client(), "available", lambda: False
    )
    monkeypatch.setattr(registry.connector_registry, "_connectors", {})
    assert await connector_context("demo-org") == ""


async def test_preamble_states_environment_facts():
    preamble = await environment_preamble("demo-org")
    assert "NOT in a CLI" in preamble
    assert "cron" in preamble
    assert "Settings → Integrations" in preamble


async def test_hermes_payload_includes_preamble_and_extra_context(monkeypatch):
    monkeypatch.setattr(hermes_mod.settings, "hermes_sidecar_url", "http://hermes.test")
    monkeypatch.setattr(hermes_mod.settings, "env", "local")
    sent = {}

    async def _fake_post(self, url, json=None, headers=None):
        sent.update(json)
        return httpx.Response(200, json={"result": "ok"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    async def _no_rag(prompt, org_id, permissions):
        return ""

    monkeypatch.setattr(hermes_mod, "_permitted_context", _no_rag)
    result = await hermes_mod.run_via_hermes(
        "summarize new info", "demo-org", extra_context="Automation context: X"
    )
    assert result == "ok"
    assert "NOT in a CLI" in sent["prompt"]
    assert "Automation context: X" in sent["prompt"]
    assert sent["prompt"].rstrip().endswith("Task: summarize new info")


# --- Phase 2: PATCH endpoint -------------------------------------------------


def _create(name="Daily digest", prompt="Summarize new connector info", cadence="daily"):
    resp = client.post(
        "/automations", json={"name": name, "prompt": prompt, "cadence": cadence}
    )
    assert resp.status_code == 200
    return resp.json()


def test_patch_updates_fields():
    auto = _create()
    resp = client.patch(
        f"/automations/{auto['id']}",
        json={"cadence": "weekly", "prompt": "Summarize weekly instead"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cadence"] == "weekly"
    assert body["prompt"] == "Summarize weekly instead"
    assert body["status"] == "active"
    client.delete(f"/automations/{auto['id']}")


def test_patch_invalid_cadence_rejected():
    auto = _create()
    resp = client.patch(f"/automations/{auto['id']}", json={"cadence": "fortnightly"})
    assert resp.status_code == 400
    client.delete(f"/automations/{auto['id']}")


def test_patch_missing_automation_404():
    assert client.patch("/automations/nope", json={"cadence": "daily"}).status_code == 404


def test_patch_cross_org_rejected():
    auto = _create()
    from db.session import get_org_id

    app.dependency_overrides[get_org_id] = lambda: "other-org"
    try:
        resp = client.patch(f"/automations/{auto['id']}", json={"cadence": "weekly"})
        assert resp.status_code == 404
    finally:
        app.dependency_overrides[get_org_id] = lambda: "demo-org"
    client.delete(f"/automations/{auto['id']}")


# --- Phase 3: planner + internal execution -----------------------------------


def test_heuristic_ambiguous_automation_proposes_nothing():
    actions = orch._heuristic_plan(
        AskRequest(org_id="demo-org", question="set up an automation"),
        "answer",
        {},
        _FakeComposio(),
    )
    assert actions == []


def test_heuristic_explicit_automation_proposes_create():
    actions = orch._heuristic_plan(
        AskRequest(
            org_id="demo-org",
            question="Create an automation: every day summarize new Google Drive files",
        ),
        "answer",
        {},
        _FakeComposio(),
        user_id="u1",
    )
    assert len(actions) == 1
    assert actions[0].action == "create_automation"
    assert actions[0].params["cadence"] == "daily"


class _FakeComposio:
    def available(self) -> bool:
        return False


@pytest.mark.anyio
async def test_confirm_internal_create_automation_creates_row():
    action = orch._record(
        "demo-org",
        "internal",
        "osai",
        "create_automation",
        {"name": "Drive digest", "prompt": "Summarize new Drive files", "cadence": "daily"},
        "Create a daily automation",
        user_id="u1",
    )
    result = await orch.confirm_action(action.id, "conv1", caller_org_id="demo-org")
    assert result.status == "executed"
    with SessionLocal() as session:
        autos = [a for a in list_automations(session, "demo-org") if a.name == "Drive digest"]
        assert autos and autos[0].cadence == "daily" and autos[0].user_id == "u1"
        client.delete(f"/automations/{autos[0].id}")


@pytest.mark.anyio
async def test_confirm_internal_cross_org_rejected():
    action = orch._record(
        "demo-org", "internal", "osai", "create_automation",
        {"name": "X", "prompt": "Y", "cadence": "daily"}, "s",
    )
    result = await orch.confirm_action(action.id, "conv1", caller_org_id="other-org")
    assert result.status == "failed"
    assert result.error == "org_mismatch"


# --- Phase 4: run context ----------------------------------------------------


def test_list_documents_since_filters_by_org_and_time():
    from datetime import timedelta

    from db.models import now_utc

    with SessionLocal() as session:
        rows = list_documents_since(session, "demo-org", None, limit=5)
        future = now_utc() + timedelta(days=1)
        assert list_documents_since(session, "demo-org", future) == []
        assert all(len(r) == 3 for r in rows)


def test_run_prompt_carries_connector_and_delta_context(monkeypatch):
    auto = _create()
    captured = {}

    async def _fake_hermes(prompt, org_id, *, user_id=None, permissions=None,
                           history=None, extra_context=""):
        captured["extra_context"] = extra_context
        return "summary result"

    import agent.automation_runner as runner

    monkeypatch.setattr(runner, "run_via_hermes", _fake_hermes)
    resp = client.post(f"/automations/{auto['id']}/run")
    assert resp.status_code == 200
    assert resp.json()["result"] == "summary result"
    assert "Automation context:" in captured["extra_context"]
    assert "New items since last run" in captured["extra_context"]
    client.delete(f"/automations/{auto['id']}")
