"""The SQL surface is admin-only (SHE-6 P0 "enforce admin authorization").

A SQL query bypasses the per-document ACL/tier model entirely: it returns
whatever the connected database role can see, unfiltered by the permissions that
gate every other answer. A non-admin member must therefore not be able to manage
sources (which hold live DB credentials) or run queries.

These tests deliberately drop the autouse auth stubs from conftest, which
override require_admin with a constant admin — with them in place the gate is
invisible and this suite would pass no matter what the routes do.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.auth import _issue_token
from db.models import Org, User
from db.session import SessionLocal, get_org_id, require_admin, require_writable_org

client = TestClient(app)
_TEST_ORG_ID = "sql-auth-test-org"


def _token_for(role: str) -> str:
    uid = f"user-{uuid.uuid4()}"
    with SessionLocal() as s:
        if s.get(Org, _TEST_ORG_ID) is None:
            s.add(Org(id=_TEST_ORG_ID, name="SQL auth test"))
        user = User(
            id=uid,
            org_id=_TEST_ORG_ID,
            email=f"{uid}@t.test",
            display_name="T",
            role=role,
            token_version=0,
        )
        s.add(user)
        s.commit()
        return _issue_token(user)


@pytest.fixture
def _real_auth():
    """Run the real auth dependencies instead of conftest's constant stubs."""
    saved = {
        k: app.dependency_overrides.pop(k, None)
        for k in (get_org_id, require_writable_org, require_admin)
    }
    yield
    for key, value in saved.items():
        if value is not None:
            app.dependency_overrides[key] = value


_MEMBER_BLOCKED = [
    ("post", "/sql/sources", {"name": "w", "dsn": "postgresql://u:p@h:5432/d"}),
    ("get", "/sql/sources", None),
    ("delete", "/sql/sources/s1", None),
    ("get", "/sql/sources/s1/schema", None),
    ("post", "/sql/plan", {"source_id": "s1", "question": "how many users?"}),
    ("post", "/sql/execute", {"source_id": "s1", "sql": "SELECT 1"}),
]


@pytest.mark.parametrize("method, path, body", _MEMBER_BLOCKED)
def test_member_cannot_reach_the_sql_surface(_real_auth, method, path, body):
    token = _token_for("member")
    resp = getattr(client, method)(
        path, headers={"Authorization": f"Bearer {token}"}, **({"json": body} if body else {})
    )
    assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"
    assert resp.json()["detail"] == "Admin role required."


@pytest.mark.parametrize("method, path, body", _MEMBER_BLOCKED)
def test_admin_passes_the_gate(_real_auth, method, path, body):
    """An admin must get past authorization. The source doesn't exist, so the
    route answers 404/422 — either way it is no longer an authorization refusal,
    which is what this asserts."""
    token = _token_for("admin")
    resp = getattr(client, method)(
        path, headers={"Authorization": f"Bearer {token}"}, **({"json": body} if body else {})
    )
    assert resp.status_code != 403, f"{method} {path} wrongly refused for an admin"


def test_anonymous_cannot_reach_the_sql_surface(_real_auth):
    """No session at all must never fall through to the data plane."""
    assert client.get("/sql/sources").status_code == 401


def test_listed_sources_never_expose_the_dsn_password(_real_auth):
    """'Never return stored DSN passwords' — the list is the one place a stored
    credential could leak back out."""
    from sqlalchemy.engine import make_url

    from api.routes.sql import _mask

    masked = _mask("postgresql://alice:sup3rs3cret@db.host:5432/warehouse")
    assert make_url(masked).password == "***"
    assert "sup3rs3cret" not in masked
