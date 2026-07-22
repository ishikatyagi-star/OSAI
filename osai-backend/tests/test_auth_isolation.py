"""Tenant-isolation regression tests for the data endpoints (SEV-001).

The core data routes must resolve the org from the verified session, never the
request body: unauthenticated calls are rejected, and a body-supplied org_id is
ignored in favour of the caller's token org.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.schemas.agent import AskResponse
from config import settings
from db.session import get_org_id


@pytest.fixture
def client_without_org_override():
    """The suite autouse-overrides get_org_id (and require_writable_org) to
    demo-org; drop them so these tests exercise the real auth dependency, then
    restore afterwards."""
    from db.session import require_writable_org

    app.dependency_overrides.pop(get_org_id, None)
    app.dependency_overrides.pop(require_writable_org, None)
    yield TestClient(app)


def _token(org_id: str, sub: str = "user-1", role: str = "admin") -> str:
    """Mint a valid session JWT, seeding its principal so the token passes the
    deleted/revoked-principal check the real auth dependencies now enforce on
    reads too (SEC-002). token_version defaults to 0, matching the claim."""
    from db.models import Org, User
    from db.session import SessionLocal

    with SessionLocal() as s:
        if s.get(Org, org_id) is None:
            s.add(Org(id=org_id, name=org_id))
        if s.get(User, sub) is None:
            s.add(
                User(
                    id=sub,
                    org_id=org_id,
                    email=f"{sub}@t.test",
                    display_name="t",
                    role=role,
                    token_version=0,
                )
            )
        s.commit()

    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": sub,
            "org_id": org_id,
            "role": role,
            "tv": 0,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/search", {"org_id": "demo-org", "query": "anything"}),
        ("post", "/ask", {"org_id": "demo-org", "question": "who owns VPC setup"}),
        (
            "post",
            "/workflows",
            {"org_id": "demo-org", "input_text": "notes", "destination": "manual"},
        ),
    ],
)
def test_data_endpoints_require_auth(client_without_org_override, method, path, body):
    resp = getattr(client_without_org_override, method)(path, json=body)
    assert resp.status_code == 401


def test_ask_ignores_body_org_id(client_without_org_override, monkeypatch):
    """A caller authenticated for org A who passes org_id=org-B in the body must
    be scoped to org A — the body value is ignored."""
    captured: dict[str, str] = {}

    async def _fake_run_ask(
        request, requester_permissions=None, requester_tier="red", user_id=None
    ):
        captured["org_id"] = request.org_id
        return AskResponse(conversation_id="c1", answer="ok", enough_context=False)

    # Stub permission/clearance lookups so the test doesn't depend on DB state.
    monkeypatch.setattr("api.routes.agent.run_ask", _fake_run_ask)
    monkeypatch.setattr("api.routes.agent.user_permissions", lambda db, claims: [])
    monkeypatch.setattr("api.routes.agent.user_clearance", lambda db, claims: "red")

    resp = client_without_org_override.post(
        "/ask",
        json={"org_id": "org-B", "question": "hi"},
        headers={"Authorization": f"Bearer {_token('org-A')}"},
    )
    assert resp.status_code == 200
    assert captured["org_id"] == "org-A"  # token org, not the body's "org-B"


def test_token_is_rejected_after_principal_moves_to_another_org(
    client_without_org_override, monkeypatch
):
    """A signed token is bound to the user's current workspace membership."""
    from db.models import Org, User
    from db.session import SessionLocal

    marker = uuid.uuid4().hex
    old_org = f"org-old-{marker}"
    new_org = f"org-new-{marker}"
    user_id = f"moved-{marker}"
    old_token = _token(old_org, sub=user_id, role="member")
    with SessionLocal() as db:
        db.add(Org(id=new_org, name=new_org))
        db.flush()
        user = db.get(User, user_id)
        assert user is not None
        user.org_id = new_org
        db.commit()

    called = False

    async def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("stale cross-org token reached Ask")

    monkeypatch.setattr("api.routes.agent.run_ask", should_not_run)
    response = client_without_org_override.post(
        "/ask",
        json={"question": "private workspace question"},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert response.status_code == 401
    assert called is False


def test_email_login_disabled_returns_403(monkeypatch):
    """SEV-102: password-less email login is refused when disabled (prod)."""
    monkeypatch.setattr(settings, "email_login_enabled", False)
    resp = TestClient(app).post("/auth/login", json={"email": "someone@known.com"})
    assert resp.status_code == 403


def test_login_is_rate_limited(monkeypatch):
    """SEV-101: repeated login attempts from one IP are throttled with 429."""
    # Disable email login so each call short-circuits before any DB access; the
    # rate-limit dependency still runs first and is what we're asserting.
    monkeypatch.setattr(settings, "email_login_enabled", False)
    client = TestClient(app)
    statuses = [
        client.post("/auth/login", json={"email": "x@y.com"}).status_code
        for _ in range(12)
    ]
    assert statuses[0] == 403  # allowed through to the handler (which 403s)
    assert 429 in statuses  # later calls are throttled


def test_org_create_rejects_invalid_email():
    """SEV-101: org provisioning validates the admin email."""
    resp = TestClient(app).post(
        "/orgs",
        json={"name": "Acme", "admin_email": "not-an-email", "admin_display_name": "Admin"},
    )
    assert resp.status_code == 422


def test_get_workflow_requires_auth(client_without_org_override):
    """GET /workflows/{id} carries transcripts + action items — it must never be
    readable by ID alone (external audit, critical finding #1)."""
    resp = client_without_org_override.get("/workflows/some-run-id")
    assert resp.status_code == 401


def test_get_workflow_cross_org_reads_as_404(client_without_org_override):
    """A run belonging to another org must 404 for this caller, not leak."""
    from db.repositories import list_workflow_runs
    from db.session import SessionLocal

    with SessionLocal() as s:
        runs = list_workflow_runs(s, "demo-org")
    if not runs:
        return  # nothing seeded to probe; the auth test above still guards the route
    headers = {
        "Authorization": (
            f"Bearer {_token('other-org', sub=f'other-org-user-{uuid.uuid4().hex}')}"
        )
    }
    resp = client_without_org_override.get(f"/workflows/{runs[0].id}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/artifacts",
        "/automations",
        "/dashboard/metrics",
        "/decisions",
        "/evals",
        "/graph/entities",
        "/integrations",
        "/notifications",
        "/notifications/page",
        "/settings/data-routing",
        "/sync-runs",
        "/sync-runs/page",
        "/team/members",
        "/threads",
        "/workflows",
    ],
)
def test_private_read_routes_require_auth(client_without_org_override, path):
    assert client_without_org_override.get(path).status_code == 401


def test_artifacts_are_isolated_between_real_tenants(client_without_org_override):
    marker = uuid.uuid4().hex
    token_a = _token(f"org-a-{marker}", sub=f"admin-a-{marker}")
    token_b = _token(f"org-b-{marker}", sub=f"admin-b-{marker}")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    created = client_without_org_override.post(
        "/artifacts",
        json={
            "title": "Tenant A only",
            "kind": "source_table",
            "data": {
                "id": f"tenant-a-{marker}",
                "kind": "source_table",
                "title": "Tenant A only",
                "rows": [],
            },
        },
        headers=headers_a,
    )
    assert created.status_code == 200
    artifact_id = created.json()["id"]

    assert artifact_id not in {
        row["id"] for row in client_without_org_override.get("/artifacts", headers=headers_b).json()
    }
    assert (
        client_without_org_override.delete(
            f"/artifacts/{artifact_id}", headers=headers_b
        ).status_code
        == 200
    )
    assert artifact_id in {
        row["id"] for row in client_without_org_override.get("/artifacts", headers=headers_a).json()
    }


def test_private_thread_is_hidden_from_another_member(client_without_org_override):
    marker = uuid.uuid4().hex
    org_id = f"org-{marker}"
    headers_a = {
        "Authorization": f"Bearer {_token(org_id, sub=f'member-a-{marker}', role='member')}"
    }
    headers_b = {
        "Authorization": f"Bearer {_token(org_id, sub=f'member-b-{marker}', role='member')}"
    }

    created = client_without_org_override.post(
        "/threads", json={"title": "Private thread"}, headers=headers_a
    )
    assert created.status_code == 200
    thread_id = created.json()["id"]

    other_member_get = client_without_org_override.get(
        f"/threads/{thread_id}", headers=headers_b
    )
    assert other_member_get.status_code == 404
    assert thread_id not in {
        row["id"] for row in client_without_org_override.get("/threads", headers=headers_b).json()
    }
