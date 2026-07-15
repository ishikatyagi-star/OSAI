"""GET /auth/session — session introspection (SHE-6 P0).

The session cookie is httpOnly, so the browser cannot read its own identity out
of it. This endpoint is how the client learns who it is and what it may do, so
that it offers the right surfaces (e.g. admin-only Data sources) instead of
guessing and rendering a 403.

It must answer from the database, not the JWT: the token carries a role snapshot
up to 30 days old, so a demotion has to take effect immediately.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.auth import _issue_token
from db.models import Org, User
from db.session import SessionLocal, get_claims, get_org_id, require_admin, require_writable_org

client = TestClient(app)


def _make_user(role: str = "member", **kwargs) -> tuple[str, str]:
    """Create a user and return (user_id, freshly issued token)."""
    uid = f"user-{uuid.uuid4()}"
    with SessionLocal() as s:
        if s.get(Org, "demo-org") is None:
            s.add(Org(id="demo-org", name="demo"))
        user = User(
            id=uid,
            org_id="demo-org",
            email=f"{uid}@t.test",
            display_name="Test Person",
            role=role,
            token_version=0,
            **kwargs,
        )
        s.add(user)
        s.commit()
        return uid, _issue_token(user)


@pytest.fixture
def _real_auth():
    """Run the real auth dependencies instead of conftest's constant stubs."""
    saved = {
        k: app.dependency_overrides.pop(k, None)
        for k in (get_claims, get_org_id, require_writable_org, require_admin)
    }
    yield
    for key, value in saved.items():
        if value is not None:
            app.dependency_overrides[key] = value


def _get(token: str):
    return client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})


def test_returns_identity_and_permissions(_real_auth):
    uid, token = _make_user(role="admin", data_tier="amber", permissions=["org:admin"])
    body = _get(token).json()
    assert body["user_id"] == uid
    assert body["org_id"] == "demo-org"
    assert body["role"] == "admin"
    assert body["is_admin"] is True
    assert body["data_tier"] == "amber"
    assert body["permissions"] == ["org:admin"]
    assert body["display_name"] == "Test Person"


def test_member_is_not_admin(_real_auth):
    _, token = _make_user(role="member")
    body = _get(token).json()
    assert body["role"] == "member"
    assert body["is_admin"] is False


def test_no_session_is_401(_real_auth):
    assert client.get("/auth/session").status_code == 401


def test_role_comes_from_the_database_not_the_stale_token(_real_auth):
    """A demoted admin must stop being admin immediately — not in 30 days when
    their token expires. This is why the endpoint reads the DB."""
    uid, token = _make_user(role="admin")
    assert _get(token).json()["is_admin"] is True

    with SessionLocal() as s:
        s.get(User, uid).role = "member"
        s.commit()

    body = _get(token).json()  # same token, which still claims role=admin
    assert body["role"] == "member"
    assert body["is_admin"] is False


def test_revoked_token_is_rejected(_real_auth):
    """Introspection must honour sign-out-everywhere like every other route
    (SEC-002) — it must not become a way to probe a revoked session."""
    uid, token = _make_user()
    assert _get(token).status_code == 200

    with SessionLocal() as s:
        s.get(User, uid).token_version += 1
        s.commit()

    assert _get(token).status_code == 401


def test_deleted_account_fails_closed(_real_auth):
    """The token still verifies after the row is gone; it must not 500 or leak."""
    uid, token = _make_user()
    with SessionLocal() as s:
        s.delete(s.get(User, uid))
        s.commit()
    assert _get(token).status_code == 401


def test_never_returns_the_session_token(_real_auth):
    """The whole point of the httpOnly cookie is that the JWT never reaches JS."""
    _, token = _make_user()
    body = _get(token).json()
    assert "token" not in body
    assert token not in str(body)
