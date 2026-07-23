"""External automation trigger API (tokened, PromptQL Program-API style)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from db.models import Automation, Org, User
from db.session import (
    SessionLocal,
    get_optional_claims,
    get_org_id,
    require_writable_org,
)

client = TestClient(app)
ORG_ID = "automation-trigger-org"


@pytest.fixture(autouse=True)
def _automation_identity():
    with SessionLocal() as session:
        if session.get(Org, ORG_ID) is None:
            session.add(Org(id=ORG_ID, name="Automation triggers"))
        user = session.scalar(
            select(User).where(User.email == "automation-trigger-tests@osai.local")
        )
        if user is None:
            user = User(
                org_id=ORG_ID,
                email="automation-trigger-tests@osai.local",
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
    previous_org = app.dependency_overrides.get(get_org_id)
    previous_write_org = app.dependency_overrides.get(require_writable_org)
    app.dependency_overrides[get_optional_claims] = lambda: claims
    app.dependency_overrides[get_org_id] = lambda: ORG_ID
    app.dependency_overrides[require_writable_org] = lambda: ORG_ID
    yield
    if previous is None:
        app.dependency_overrides.pop(get_optional_claims, None)
    else:
        app.dependency_overrides[get_optional_claims] = previous
    if previous_org is None:
        app.dependency_overrides.pop(get_org_id, None)
    else:
        app.dependency_overrides[get_org_id] = previous_org
    if previous_write_org is None:
        app.dependency_overrides.pop(require_writable_org, None)
    else:
        app.dependency_overrides[require_writable_org] = previous_write_org


def _mk_automation() -> str:
    resp = client.post(
        "/automations",
        json={
            "name": "Pipeline risk report",
            "prompt": "List risky opportunities",
            "cadence": "manual",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_mint_trigger_and_revoke():
    aid = _mk_automation()
    minted = client.post(f"/automations/{aid}/token").json()
    token = minted["token"]
    assert token.startswith("osak_")

    # Listing shows presence, never the token itself.
    row = next(a for a in client.get("/automations").json() if a["id"] == aid)
    assert row["has_trigger_token"] is True

    with patch(
        "api.routes.automations.execute_automation",
        new=AsyncMock(return_value={"ok": True, "result": "2 risky opps"}),
    ):
        # External call: token only, no org auth.
        r = TestClient(app).post(
            f"/automations/{aid}/trigger",
            headers={
                "X-Trigger-Token": token,
                "Idempotency-Key": "mint-trigger-test-1",
            },
        )
        assert r.status_code == 200 and r.json()["ok"] is True

        # Wrong/missing token → 401.
        assert (
            TestClient(app)
            .post(f"/automations/{aid}/trigger", headers={"X-Trigger-Token": "osak_wrong"})
            .status_code
            == 401
        )
        assert TestClient(app).post(f"/automations/{aid}/trigger").status_code == 401

    # Revoke kills external access.
    assert client.delete(f"/automations/{aid}/token").json()["revoked"] is True
    assert (
        TestClient(app)
        .post(f"/automations/{aid}/trigger", headers={"X-Trigger-Token": token})
        .status_code
        == 401
    )
    client.delete(f"/automations/{aid}")


def test_paused_automation_conflicts():
    aid = _mk_automation()
    token = client.post(f"/automations/{aid}/token").json()["token"]
    client.patch(f"/automations/{aid}", json={"status": "paused"})
    r = TestClient(app).post(f"/automations/{aid}/trigger", headers={"X-Trigger-Token": token})
    assert r.status_code == 409
    client.delete(f"/automations/{aid}")


def test_trigger_replays_completed_result_and_rejects_payload_conflict():
    aid = _mk_automation()
    token = client.post(f"/automations/{aid}/token").json()["token"]
    headers = {
        "X-Trigger-Token": token,
        "Idempotency-Key": "deploy-hook-request-1",
    }
    execution = AsyncMock(return_value={"ok": True, "result": "accepted"})

    with patch("api.routes.automations.execute_automation", new=execution):
        first = TestClient(app).post(
            f"/automations/{aid}/trigger",
            headers=headers,
            json={"event": "deploy"},
        )
        replay = TestClient(app).post(
            f"/automations/{aid}/trigger",
            headers=headers,
            json={"event": "deploy"},
        )
        conflict = TestClient(app).post(
            f"/automations/{aid}/trigger",
            headers=headers,
            json={"event": "rollback"},
        )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert conflict.status_code == 409
    assert execution.await_count == 1
    client.delete(f"/automations/{aid}")


def test_trigger_requires_bounded_idempotency_key():
    aid = _mk_automation()
    token = client.post(f"/automations/{aid}/token").json()["token"]
    with patch("api.routes.automations.execute_automation", new=AsyncMock()) as execution:
        response = TestClient(app).post(
            f"/automations/{aid}/trigger",
            headers={"X-Trigger-Token": token},
        )
    assert response.status_code == 400
    execution.assert_not_awaited()
    client.delete(f"/automations/{aid}")


def test_verified_tenant_trigger_budget_is_enforced(monkeypatch):
    import api.routes.automations as route

    aid = _mk_automation()
    token = client.post(f"/automations/{aid}/token").json()["token"]
    monkeypatch.setattr(route, "WORKFLOW_RUN_BUDGET", (1, 60))
    execution = AsyncMock(return_value={"ok": True})
    with patch("api.routes.automations.execute_automation", new=execution):
        first = TestClient(app).post(
            f"/automations/{aid}/trigger",
            headers={
                "X-Trigger-Token": token,
                "Idempotency-Key": "tenant-budget-key-1",
            },
        )
        limited = TestClient(app).post(
            f"/automations/{aid}/trigger",
            headers={
                "X-Trigger-Token": token,
                "Idempotency-Key": "tenant-budget-key-2",
            },
        )
    assert first.status_code == 200
    assert limited.status_code == 429
    assert execution.await_count == 1
    client.delete(f"/automations/{aid}")


@pytest.mark.parametrize("authorization", [None, "valid-demo-session"])
def test_demo_automation_token_cannot_mutate_shared_demo(authorization):
    import jwt

    from api.routes.automations import _hash_token
    from config import settings

    token = "osak_demo_external_trigger"
    automation_id = "demo-external-trigger"
    with SessionLocal() as session:
        if session.get(Org, settings.default_org_id) is None:
            session.add(Org(id=settings.default_org_id, name="Demo"))
            session.flush()
        existing = session.get(Automation, automation_id)
        if existing is None:
            session.add(
                Automation(
                    id=automation_id,
                    org_id=settings.default_org_id,
                    name="Demo trigger",
                    prompt="Do not run",
                    cadence="manual",
                    trigger_token_hash=_hash_token(token),
                )
            )
        session.commit()

    headers = {"X-Trigger-Token": token}
    if authorization:
        session_token = jwt.encode(
            {"org_id": settings.default_org_id, "sub": "demo-user"},
            settings.jwt_secret,
            algorithm="HS256",
        )
        headers["Authorization"] = f"Bearer {session_token}"
    response = TestClient(app).post(
        f"/automations/{automation_id}/trigger",
        headers=headers,
    )
    assert response.status_code == 403

    with SessionLocal() as session:
        row = session.get(Automation, automation_id)
        if row is not None:
            session.delete(row)
            session.commit()
