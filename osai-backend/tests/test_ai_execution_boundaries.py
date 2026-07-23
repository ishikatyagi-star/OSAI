"""Security boundaries for unattended and administrative AI execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app
from api.schemas.eval import EvalRun
from config import settings
from db.models import Automation, Org, User
from db.session import SessionLocal, get_optional_claims, require_admin

client = TestClient(app)


def test_unclassified_connector_cloud_requires_admin_and_red_policy(monkeypatch):
    import agent.orchestrator as orchestrator
    import llm.policy as policy

    routing = {
        "normal": {"allowed_connectors": [], "llm_allowed": True},
        "amber": {"allowed_connectors": [], "llm_allowed": False},
        "red": {"allowed_connectors": [], "llm_allowed": False},
    }
    monkeypatch.setattr(policy, "load_data_routing", lambda _org_id: routing)

    assert not orchestrator._unclassified_connector_cloud_allowed("org-1", [])
    assert not orchestrator._unclassified_connector_cloud_allowed(
        "org-1", ["role:admin"]
    )

    routing["red"]["llm_allowed"] = True
    assert not orchestrator._unclassified_connector_cloud_allowed(
        "org-1", ["source:gmail"]
    )
    assert orchestrator._unclassified_connector_cloud_allowed(
        "org-1", ["role:admin"]
    )


def _user(
    *, role: str = "member", tier: str = "normal", permissions: list[str] | None = None
) -> User:
    marker = uuid4().hex
    with SessionLocal() as db:
        if db.get(Org, "demo-org") is None:
            db.add(Org(id="demo-org", name="Demo"))
        user = User(
            id=f"ai-boundary-{marker}",
            org_id="demo-org",
            email=f"ai-boundary-{marker}@test.invalid",
            display_name="AI Boundary",
            role=role,
            data_tier=tier,
            permissions=permissions or [],
            token_version=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def _claims(user: User) -> dict:
    return {
        "sub": user.id,
        "org_id": user.org_id,
        "role": user.role,
        "tv": user.token_version,
    }


@pytest.fixture
def as_user():
    previous = app.dependency_overrides.get(get_optional_claims)

    def use(user: User) -> None:
        app.dependency_overrides[get_optional_claims] = lambda: _claims(user)

    yield use
    if previous is None:
        app.dependency_overrides.pop(get_optional_claims, None)
    else:
        app.dependency_overrides[get_optional_claims] = previous


def test_automation_is_bound_to_creator_and_hidden_from_other_member(as_user):
    owner = _user(tier="amber", permissions=["source:drive"])
    other = _user()
    admin = _user(role="admin", permissions=["org:admin", "source:all"])
    as_user(owner)
    created = client.post(
        "/automations",
        json={"name": "Private digest", "prompt": "Summarize Drive", "cadence": "daily"},
    )
    assert created.status_code == 200, created.text
    automation_id = created.json()["id"]
    try:
        with SessionLocal() as db:
            row = db.get(Automation, automation_id)
            assert row.user_id == owner.id
            row.last_result = "OWNER PRIVATE RESULT"
            db.commit()

        as_user(other)
        assert automation_id not in {row["id"] for row in client.get("/automations").json()}
        assert (
            client.patch(f"/automations/{automation_id}", json={"name": "stolen"}).status_code
            == 404
        )
        assert client.post(f"/automations/{automation_id}/run").status_code == 404
        assert client.post(f"/automations/{automation_id}/token").status_code == 404

        as_user(admin)
        admin_rows = client.get("/automations").json()
        assert automation_id not in {row["id"] for row in admin_rows}
        assert "OWNER PRIVATE RESULT" not in str(admin_rows)
        assert client.post(f"/automations/{automation_id}/run").status_code == 404
        assert client.post(f"/automations/{automation_id}/token").status_code == 404
        assert (
            client.patch(f"/automations/{automation_id}", json={"name": "admin"}).status_code
            == 404
        )
        assert client.delete(f"/automations/{automation_id}").status_code == 404
    finally:
        with SessionLocal() as db:
            row = db.get(Automation, automation_id)
            if row is not None:
                db.delete(row)
                db.commit()


@pytest.mark.anyio
async def test_internal_automation_actions_require_owner_and_enforce_acl():
    import agent.orchestrator as orchestrator

    owner = _user()
    other = _user()
    admin = _user(role="admin", permissions=["org:admin", "source:all"])
    ownerless = orchestrator._record(
        "demo-org",
        "internal",
        "osai",
        "create_automation",
        {"name": "Ownerless", "prompt": "Must not exist", "cadence": "daily"},
        "Create an ownerless automation",
    )
    result = await orchestrator.confirm_action(
        ownerless.id, "conversation", caller_org_id="demo-org"
    )
    assert result.status == "failed"
    assert result.error == "automation_owner_required"

    with SessionLocal() as db:
        auto = Automation(
            org_id="demo-org",
            user_id=owner.id,
            name="Owner only",
            prompt="Private task",
            cadence="manual",
        )
        db.add(auto)
        db.commit()
        automation_id = auto.id
    try:
        unauthorized = orchestrator._record(
            "demo-org",
            "internal",
            "osai",
            "update_automation",
            {"automation_id": automation_id, "name": "Taken over"},
            "Update someone else's automation",
            user_id=other.id,
        )
        result = await orchestrator.confirm_action(
            unauthorized.id,
            "conversation",
            caller_org_id="demo-org",
            caller_user_id=other.id,
        )
        assert result.status == "failed"
        assert result.error == "automation_missing"
        admin_attempt = orchestrator._record(
            "demo-org",
            "internal",
            "osai",
            "update_automation",
            {"automation_id": automation_id, "name": "Admin takeover"},
            "Update another user's automation",
            user_id=admin.id,
        )
        result = await orchestrator.confirm_action(
            admin_attempt.id,
            "conversation",
            caller_org_id="demo-org",
            caller_user_id=admin.id,
            caller_is_admin=True,
        )
        assert result.status == "failed"
        assert result.error == "automation_missing"
        with SessionLocal() as db:
            assert db.get(Automation, automation_id).name == "Owner only"
    finally:
        with SessionLocal() as db:
            auto = db.get(Automation, automation_id)
            if auto is not None:
                db.delete(auto)
                db.commit()


@pytest.mark.anyio
async def test_shared_runner_uses_current_creator_context_for_hermes_and_fallback(monkeypatch):
    owner = _user(tier="amber", permissions=["source:drive"])
    with SessionLocal() as db:
        auto = Automation(
            org_id=owner.org_id,
            user_id=owner.id,
            name="Creator-scoped",
            prompt="Summarize Drive",
            cadence="manual",
        )
        db.add(auto)
        db.commit()
        db.refresh(auto)

        import agent.automation_runner as runner

        captured: dict[str, dict] = {}

        async def fake_hermes(prompt, org_id, **kwargs):
            captured["hermes"] = kwargs
            return None

        async def fake_ask(request, **kwargs):
            captured["ask"] = kwargs
            return SimpleNamespace(answer="safe", citations=[])

        async def no_context(_org_id):
            return ""

        async def no_delivery(_auto, _result, **_kwargs):
            return None

        monkeypatch.setattr(runner, "run_via_hermes", fake_hermes)
        monkeypatch.setattr(runner, "run_ask", fake_ask)
        monkeypatch.setattr(runner, "connector_context", no_context)
        monkeypatch.setattr(runner, "list_documents_since", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(runner, "record_automation_run", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runner, "_deliver", no_delivery)

        await runner.execute_automation(db, auto)

    expected_permissions = {"source:drive", f"user:{owner.id}"}
    assert set(captured["hermes"]["permissions"]) == expected_permissions
    assert captured["hermes"]["requester_tier"] == "amber"
    assert captured["hermes"]["user_id"] == owner.id
    assert set(captured["ask"]["requester_permissions"]) == expected_permissions
    assert captured["ask"]["requester_tier"] == "amber"
    assert captured["ask"]["user_id"] == owner.id


@pytest.mark.anyio
@pytest.mark.parametrize("creator_state", ["missing", "deleted"])
async def test_shared_runner_fails_closed_without_current_creator(creator_state):
    owner = _user()
    with SessionLocal() as db:
        auto = Automation(
            org_id=owner.org_id,
            user_id=None if creator_state == "missing" else owner.id,
            name="Legacy",
            prompt="Should not run",
            cadence="manual",
        )
        db.add(auto)
        db.commit()
        db.refresh(auto)
        if creator_state == "deleted":
            db.delete(db.get(User, owner.id))
            db.commit()

        from agent.automation_runner import execute_automation

        with pytest.raises(HTTPException) as exc:
            await execute_automation(db, auto)
    assert exc.value.status_code == 409


@pytest.mark.anyio
async def test_hermes_retrieval_receives_tier_and_user(monkeypatch):
    import agent.hermes_client as hermes

    captured = {}

    async def fake_retrieve(request):
        captured["request"] = request
        return SimpleNamespace(answer="ok", citations=[])

    monkeypatch.setattr(hermes, "retrieve_answer", fake_retrieve)
    await hermes._permitted_context(
        "question",
        "org-1",
        ["source:drive", "user:u1"],
        requester_tier="amber",
        requester_user_id="u1",
    )
    request = captured["request"]
    assert request.requester_permissions == ["source:drive", "user:u1"]
    assert request.requester_tier == "amber"
    assert request.requester_user_id == "u1"


@pytest.mark.anyio
async def test_live_composio_read_defaults_closed_for_non_admin():
    from connectors.composio_live import live_read_context

    fake = SimpleNamespace(available=lambda: True)
    assert (
        await live_read_context(
            "org-1", "list linear issues", requester_permissions=["source:linear"], client=fake
        )
        == ""
    )


def test_evals_execute_only_via_admin_post(monkeypatch):
    import api.routes.evals as route

    result = EvalRun(
        run_id="run-1",
        created_at="2026-01-01T00:00:00Z",
        model_route="mock-fallback",
        pass_rate=0,
        total=0,
        passed=0,
        failed=0,
        cases=[],
    )
    fake = AsyncMock(return_value=result)
    monkeypatch.setattr(route, "run_evals", fake)

    assert client.get("/evals").status_code == 405
    response = client.post("/evals")
    assert response.status_code == 200, response.text
    assert fake.await_args.kwargs == {
        "requester_permissions": ["role:admin", "user:test-admin"],
        "requester_tier": "red",
        "requester_user_id": "test-admin",
    }


def test_evals_reject_current_non_admin():
    member = _user(role="member")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            **_claims(member),
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    previous = app.dependency_overrides.pop(require_admin, None)
    try:
        response = client.post("/evals", headers={"Authorization": f"Bearer {token}"})
    finally:
        if previous is not None:
            app.dependency_overrides[require_admin] = previous
    assert response.status_code == 403
