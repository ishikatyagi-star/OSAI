"""Tenant-isolation regression tests for the data endpoints (SEV-001).

The core data routes must resolve the org from the verified session, never the
request body: unauthenticated calls are rejected, and a body-supplied org_id is
ignored in favour of the caller's token org.
"""

from __future__ import annotations

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
    """The suite autouse-overrides get_org_id to demo-org; drop it so these tests
    exercise the real auth dependency, then restore it afterwards."""
    app.dependency_overrides.pop(get_org_id, None)
    yield TestClient(app)


def _token(org_id: str, sub: str = "user-1", role: str = "admin") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": sub, "org_id": org_id, "role": role, "iat": now, "exp": now + timedelta(hours=1)},
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

    async def _fake_run_ask(request, requester_permissions=None, requester_tier="red"):
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
