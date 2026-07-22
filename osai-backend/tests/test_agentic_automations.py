"""Agentic automations: connector-aware context, conversational creation via the
propose→confirm loop, PATCH editing, and run-time "what's new" context."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import agent.hermes_client as hermes_mod
import agent.orchestrator as orch
from agent.context import connector_context, environment_preamble
from api.main import app
from api.routes.automations import get_scheduler_available
from api.schemas.agent import AskRequest
from db.models import Org, SourceDocumentRecord, User
from db.repositories import list_automations, list_documents_since
from db.session import SessionLocal, get_optional_claims

client = TestClient(app)


@pytest.fixture(autouse=True)
def _automation_identity():
    with SessionLocal() as session:
        if session.get(Org, "demo-org") is None:
            session.add(Org(id="demo-org", name="Demo"))
        user = session.scalar(select(User).where(User.email == "automation-tests@osai.local"))
        if user is None:
            user = User(
                org_id="demo-org",
                email="automation-tests@osai.local",
                display_name="Automation Tests",
                role="admin",
                permissions=["org:admin", "source:all"],
            )
            session.add(user)
        session.commit()
        session.refresh(user)
        claims = {
            "sub": user.id,
            "org_id": user.org_id,
            "role": user.role,
            "tv": user.token_version,
        }
    previous = app.dependency_overrides.get(get_optional_claims)
    app.dependency_overrides[get_optional_claims] = lambda: claims
    yield user.id
    if previous is None:
        app.dependency_overrides.pop(get_optional_claims, None)
    else:
        app.dependency_overrides[get_optional_claims] = previous


# --- Phase 1: connector context + environment preamble ----------------------


async def test_connector_context_empty_when_nothing_available(monkeypatch):
    from connectors import composio_tool
    from db import repositories

    monkeypatch.setattr(
        composio_tool.get_default_composio_client(), "available", lambda: False
    )
    monkeypatch.setattr(repositories, "list_integrations", lambda _session, _org_id: [])
    assert await connector_context("demo-org") == ""


async def test_connector_context_is_org_scoped_and_omits_account_identity(monkeypatch):
    from connectors import composio_tool
    from db import repositories

    class _Client:
        @staticmethod
        def available():
            return True

        @staticmethod
        async def list_connections(_org_id):
            return [
                {"toolkit": "gmail", "status": "ACTIVE", "email": "private@example.test"},
                {"toolkit": "notion", "status": "INITIATED"},
            ]

    monkeypatch.setattr(composio_tool, "get_default_composio_client", lambda: _Client())
    monkeypatch.setattr(
        repositories,
        "list_integrations",
        lambda _session, _org_id: [
            {"key": "slack", "auth_state": "connected", "capabilities": ["sync"]},
            {"key": "freshdesk", "auth_state": "not_configured", "capabilities": ["sync"]},
        ],
    )

    context = await connector_context("demo-org")

    assert "gmail" in context
    assert "slack" in context
    assert "private@example.test" not in context
    assert "notion" not in context
    assert "freshdesk" not in context
    assert "latest successful sync" in context


async def test_preamble_states_environment_facts():
    preamble = await environment_preamble("demo-org")
    assert "NOT in a CLI" in preamble
    assert "cron" in preamble
    assert "Settings → Integrations" in preamble


async def test_preamble_forbids_fake_process_narration_and_fabrication():
    # Regression: the agent narrated fake work ("scanning your emails, please
    # wait") and invented data. The preamble must explicitly forbid both.
    preamble = (await environment_preamble("demo-org")).lower()
    assert "single turn" in preamble
    assert "please wait" in preamble  # named as a thing NOT to say
    assert "never invent" in preamble or "do not invent" in preamble
    assert "john doe" in preamble  # named as a placeholder NOT to use


async def test_hermes_payload_includes_preamble_and_extra_context(monkeypatch):
    monkeypatch.setattr(hermes_mod.settings, "hermes_sidecar_url", "http://hermes.test")
    monkeypatch.setattr(hermes_mod.settings, "env", "local")
    sent = {}

    async def _fake_post(self, url, json=None, headers=None):
        sent.update(json)
        return httpx.Response(200, json={"result": "ok"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    async def _no_rag(prompt, org_id, permissions, *, requester_tier, requester_user_id):
        return ""

    monkeypatch.setattr(hermes_mod, "_permitted_context", _no_rag)
    result = await hermes_mod.run_via_hermes(
        "summarize new info",
        "demo-org",
        user_id=None,
        permissions=[],
        requester_tier="red",
        extra_context="Automation context: X",
        extra_context_cloud_safe=True,
    )
    assert result == "ok"
    assert "NOT in a CLI" in sent["prompt"]
    assert "Automation context: X" in sent["prompt"]
    assert sent["prompt"].rstrip().endswith("Task: summarize new info")

    sent.clear()
    await hermes_mod.run_via_hermes(
        "summarize new info",
        "demo-org",
        user_id=None,
        permissions=[],
        requester_tier="red",
        extra_context="RESTRICTED UNCLASSIFIED PAYLOAD",
    )
    assert "RESTRICTED UNCLASSIFIED PAYLOAD" not in sent["prompt"]


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


def test_recurring_cadence_rejected_without_scheduler():
    app.dependency_overrides[get_scheduler_available] = lambda: False
    try:
        resp = client.post(
            "/automations",
            json={
                "name": "No ghost schedule",
                "prompt": "Summarize",
                "cadence": "daily",
            },
        )
        assert resp.status_code == 503
        assert "scheduler heartbeat" in resp.json()["detail"].lower()

        manual = client.post(
            "/automations",
            json={
                "name": "Manual is honest",
                "prompt": "Summarize",
                "cadence": "manual",
            },
        )
        assert manual.status_code == 200
        client.delete(f"/automations/{manual.json()['id']}")
    finally:
        app.dependency_overrides[get_scheduler_available] = lambda: True


def test_patch_missing_automation_404():
    assert client.patch("/automations/nope", json={"cadence": "daily"}).status_code == 404


def test_patch_cross_org_rejected():
    auto = _create()
    # PATCH is a write route, so it resolves the org via require_writable_org;
    # point that at another org to prove cross-org edits 404.
    from db.session import require_writable_org

    app.dependency_overrides[require_writable_org] = lambda: "other-org"
    try:
        resp = client.patch(f"/automations/{auto['id']}", json={"cadence": "weekly"})
        assert resp.status_code == 404
    finally:
        app.dependency_overrides[require_writable_org] = lambda: "demo-org"
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


@pytest.mark.parametrize(
    ("question", "tools", "composio"),
    [
        ("Search the web for current release notes", {}, True),
        ("Raise a support ticket for the login bug", {"create_freshdesk_ticket": {}}, False),
        ("Notify the team in Slack about the release", {"post_slack_message": {}}, False),
        ("Create a Notion page for this plan", {"create_notion_page": {}}, False),
    ],
)
def test_heuristic_connector_actions_preserve_proposer(question, tools, composio):
    class _Composio:
        def available(self) -> bool:
            return composio

    actions = orch._heuristic_plan(
        AskRequest(org_id="demo-org", question=question),
        "answer",
        tools,
        _Composio(),
        user_id="requesting-user",
    )
    assert len(actions) == 1
    assert orch._PROPOSED[actions[0].id]["user_id"] == "requesting-user"


class _FakeComposio:
    def available(self) -> bool:
        return False


@pytest.mark.anyio
async def test_confirm_internal_create_automation_creates_row(_automation_identity):
    action = orch._record(
        "demo-org",
        "internal",
        "osai",
        "create_automation",
        {"name": "Drive digest", "prompt": "Summarize new Drive files", "cadence": "daily"},
        "Create a daily automation",
        user_id=_automation_identity,
    )
    result = await orch.confirm_action(action.id, "conv1", caller_org_id="demo-org")
    assert result.status == "executed"
    with SessionLocal() as session:
        autos = [a for a in list_automations(session, "demo-org") if a.name == "Drive digest"]
        assert autos and autos[0].cadence == "daily" and autos[0].user_id == _automation_identity
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
        rows = list_documents_since(
            session,
            "demo-org",
            None,
            requester_permissions=["role:admin"],
            requester_tier="red",
            limit=5,
        )
        future = now_utc() + timedelta(days=1)
        assert (
            list_documents_since(
                session,
                "demo-org",
                future,
                requester_permissions=["role:admin"],
                requester_tier="red",
            )
            == []
        )
        assert all(len(r) == 4 for r in rows)


def test_list_documents_since_applies_owner_acl_and_tier(_automation_identity):
    marker = uuid4().hex
    visible_title = f"visible-{marker}"
    hidden_private_title = f"private-{marker}"
    hidden_red_title = f"red-{marker}"
    doc_ids = [f"automation-context-{marker}-{suffix}" for suffix in ("visible", "private", "red")]
    with SessionLocal() as session:
        session.add_all(
            [
                SourceDocumentRecord(
                    id=doc_ids[0],
                    org_id="demo-org",
                    source_type="upload",
                    external_id=doc_ids[0],
                    title=visible_title,
                    text="visible",
                    permissions=[f"user:{_automation_identity}"],
                    data_tier="normal",
                ),
                SourceDocumentRecord(
                    id=doc_ids[1],
                    org_id="demo-org",
                    source_type="upload",
                    external_id=doc_ids[1],
                    title=hidden_private_title,
                    text="private",
                    permissions=["user:somebody-else"],
                    data_tier="normal",
                ),
                SourceDocumentRecord(
                    id=doc_ids[2],
                    org_id="demo-org",
                    source_type="upload",
                    external_id=doc_ids[2],
                    title=hidden_red_title,
                    text="restricted",
                    permissions=["source:all"],
                    data_tier="red",
                ),
            ]
        )
        session.commit()
        try:
            rows = list_documents_since(
                session,
                "demo-org",
                None,
                requester_permissions=[f"user:{_automation_identity}"],
                requester_tier="normal",
            )
            titles = {title for _source, title, _ingested, _tier in rows}
            assert visible_title in titles
            assert hidden_private_title not in titles
            assert hidden_red_title not in titles
        finally:
            session.query(SourceDocumentRecord).filter(SourceDocumentRecord.id.in_(doc_ids)).delete(
                synchronize_session=False
            )
            session.commit()


def test_run_prompt_carries_connector_and_delta_context(monkeypatch):
    auto = _create()
    captured = {}

    async def _fake_hermes(
        prompt,
        org_id,
        *,
        user_id,
        permissions,
        requester_tier,
        history=None,
        extra_context="",
        extra_context_cloud_safe=False,
    ):
        captured["extra_context"] = extra_context
        return "summary result"

    import agent.automation_runner as runner

    monkeypatch.setattr(runner, "run_via_hermes", _fake_hermes)
    from db.models import now_utc

    monkeypatch.setattr(
        runner,
        "list_documents_since",
        lambda *_args, **_kwargs: [
            ("drive", "RESTRICTED TITLE", now_utc(), "red"),
            ("notion", "Cloud-safe title", now_utc(), "normal"),
        ],
    )
    resp = client.post(f"/automations/{auto['id']}/run")
    assert resp.status_code == 200
    assert resp.json()["result"] == "summary result"
    assert "Automation context:" in captured["extra_context"]
    assert "New items since last run" in captured["extra_context"]
    assert "Cloud-safe title" in captured["extra_context"]
    assert "RESTRICTED TITLE" not in captured["extra_context"]
    assert "omitted from this context" in captured["extra_context"]
    client.delete(f"/automations/{auto['id']}")
