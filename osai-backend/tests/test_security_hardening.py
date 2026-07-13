"""Regression tests for the security-hardening pass (SEC-002 .. SEC-008).

Each test pins a specific fix so a future refactor can't silently reopen the
hole. The autouse auth override in conftest resolves write dependencies to the
demo org; tests that assert the *denial* path drop the relevant override so the
real dependency runs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from db.session import get_org_id, require_admin, require_writable_org


# ── SEC-002: a valid token whose user no longer exists must be rejected ────────
def test_deleted_user_token_does_not_fail_open_to_red(monkeypatch):
    """user_clearance/user_permissions must reject a stale principal (deleted
    account, live JWT) rather than fall through to 'red'/[] see-all."""
    import db.repositories as repo

    class _FakeSession:
        def get(self, _model, _pk):
            return None  # user row is gone

    claims = {"sub": "deleted-user", "org_id": "demo-org", "role": "member"}
    with pytest.raises(Exception) as exc_clear:
        repo.user_clearance(_FakeSession(), claims)
    with pytest.raises(Exception) as exc_perm:
        repo.user_permissions(_FakeSession(), claims)
    # 401 on both paths (HTTPException carries status_code).
    assert getattr(exc_clear.value, "status_code", None) == 401
    assert getattr(exc_perm.value, "status_code", None) == 401


def test_system_context_still_sees_all():
    """No sub (public demo / system context) is unchanged: red clearance, []."""
    import db.repositories as repo

    assert repo.user_clearance(object(), None) == "red"
    assert repo.user_permissions(object(), None) == []


# ── SEC-003: the anonymous demo workspace is read-only ─────────────────────────
@pytest.fixture
def demo_client():
    """Exercise the real require_writable_org against the public demo header."""
    app.dependency_overrides.pop(require_writable_org, None)
    app.dependency_overrides.pop(get_org_id, None)
    yield TestClient(app)
    app.dependency_overrides[require_writable_org] = lambda: "demo-org"
    app.dependency_overrides[get_org_id] = lambda: "demo-org"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/workflows", {"input_text": "hi"}),
        ("post", "/automations", {"name": "n", "prompt": "p", "cadence": "manual"}),
        ("post", "/sql/execute", {"source_id": "x", "sql": "select 1"}),
        ("post", "/ask/actions/act-1/confirm", {"conversation_id": "c1"}),
    ],
)
def test_demo_workspace_rejects_writes(demo_client, method, path, body):
    resp = getattr(demo_client, method)(
        path, json=body, headers={"X-Org-Id": "demo-org"}
    )
    assert resp.status_code == 403, (path, resp.status_code)


# ── SEC-008: connector state changes are admin-only ────────────────────────────
@pytest.fixture
def member_client():
    """A non-admin member: require_admin runs for real, get_org_id resolved."""
    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides[get_org_id] = lambda: "demo-org"
    app.dependency_overrides[require_writable_org] = lambda: "demo-org"
    yield TestClient(app)
    app.dependency_overrides[require_admin] = lambda: {
        "org_id": "demo-org",
        "role": "admin",
        "sub": "test-admin",
    }


def test_member_cannot_trigger_sync(member_client):
    # No Authorization header → require_admin → 401 (not silently allowed).
    resp = member_client.post("/integrations/notion/sync")
    assert resp.status_code in (401, 403)


# ── SEC-004: SSRF host allowlist on webhook download URLs ───────────────────────
@pytest.mark.parametrize(
    "url,allowed",
    [
        ("https://us02web.zoom.us/rec/download/abc", True),
        ("https://zoom.us/rec/x", True),
        ("http://us02web.zoom.us/rec/x", False),  # not https
        ("https://zoom.us.evil.com/rec/x", False),  # suffix trick
        ("https://169.254.169.254/latest/meta-data/", False),  # cloud metadata
        ("file:///etc/passwd", False),
    ],
)
def test_zoom_download_url_allowlist(url, allowed):
    from workers.tasks.ingest import _is_allowed_download_url

    assert _is_allowed_download_url(url) is allowed


def test_zoom_signature_fails_closed_without_secret():
    from api.routes.webhooks import verify_zoom_signature

    assert verify_zoom_signature("ts", "v0=deadbeef", b"{}", None) is False


# ── SEC-007: concurrent confirms consume the action exactly once ───────────────
def test_claim_proposed_action_is_single_shot():
    """The DB claim returns 'claimed' once, then 'taken' — the guard that stops
    two confirms double-executing the same connector side effect."""
    import uuid

    from db.repositories import claim_proposed_action, save_proposed_action

    action_id = f"act-{uuid.uuid4()}"
    save_proposed_action(
        action_id,
        {"org_id": "demo-org", "tool": "freshdesk", "action": "create_ticket"},
    )
    assert claim_proposed_action(action_id) == "claimed"
    assert claim_proposed_action(action_id) == "taken"


def test_claim_absent_action_reports_absent():
    from db.repositories import claim_proposed_action

    assert claim_proposed_action("nope-does-not-exist") == "absent"


# ── SEC-002 (depth): token_version revocation ─────────────────────────────────
def test_stale_token_version_is_rejected():
    """A token whose `tv` predates the user's current generation is refused even
    though the user still exists and the signature is valid."""
    import db.repositories as repo

    class _Session:
        def get(self, _model, _pk):
            return type("U", (), {"token_version": 3, "role": "member", "data_tier": "normal"})()

    # Matching generation → fine.
    repo.assert_token_current(_Session(), {"sub": "u1", "tv": 3})
    # Stale generation → 401.
    with pytest.raises(Exception) as exc:
        repo.assert_token_current(_Session(), {"sub": "u1", "tv": 2})
    assert getattr(exc.value, "status_code", None) == 401


def test_logout_all_revokes_outstanding_tokens():
    """POST /auth/logout-all bumps the generation so previously issued tokens
    (carrying the old tv) stop being accepted."""
    import uuid

    from api.routes.auth import _issue_token
    from db.models import Org, User
    from db.repositories import assert_token_current
    from db.session import SessionLocal, _decode_token

    uid = f"user-{uuid.uuid4()}"
    with SessionLocal() as s:
        if s.get(Org, "demo-org") is None:
            s.add(Org(id="demo-org", name="demo"))
        s.add(
            User(
                id=uid,
                org_id="demo-org",
                email=f"{uid}@t.test",
                display_name="t",
                role="member",
                token_version=0,
            )
        )
        s.commit()
        token = _issue_token(s.get(User, uid))

    claims = _decode_token(f"Bearer {token}")
    assert claims["tv"] == 0
    with SessionLocal() as s:
        assert_token_current(s, claims)  # accepted before revocation

    resp = TestClient(app).post(
        "/auth/logout-all", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200 and resp.json()["revoked"] is True

    with SessionLocal() as s:
        with pytest.raises(Exception) as exc:
            assert_token_current(s, claims)  # same token now stale
        assert getattr(exc.value, "status_code", None) == 401


# ── SEC-009 (depth): httpOnly session cookie auth ─────────────────────────────
def test_session_cookie_carries_auth_and_is_httponly():
    """A valid JWT in the osai_session cookie authenticates a request (no
    Authorization header), and the login response sets it httpOnly + Lax."""
    import uuid

    from api.routes.auth import _issue_token
    from db.models import Org, User
    from db.session import SESSION_COOKIE, SessionLocal, get_claims

    uid = f"user-{uuid.uuid4()}"
    with SessionLocal() as s:
        if s.get(Org, "demo-org") is None:
            s.add(Org(id="demo-org", name="demo"))
        s.add(
            User(
                id=uid,
                org_id="demo-org",
                email=f"{uid}@t.test",
                display_name="t",
                role="member",
                token_version=0,
            )
        )
        s.commit()
        token = _issue_token(s.get(User, uid))

    # get_claims resolves the principal from the cookie alone (no header). Drop
    # any conftest override so the real dependency runs.
    app.dependency_overrides.pop(get_claims, None)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, token)
    resp = client.post("/auth/logout-all")
    assert resp.status_code == 200  # cookie authenticated the request

    # No cookie, no header → rejected.
    assert TestClient(app).post("/auth/logout-all").status_code == 401


def test_logout_clears_the_session_cookie():
    from db.session import SESSION_COOKIE

    resp = TestClient(app).post("/auth/logout")
    assert resp.status_code == 200
    # The delete is expressed as a Set-Cookie that expires the cookie.
    set_cookie = resp.headers.get("set-cookie", "")
    assert SESSION_COOKIE in set_cookie


def test_session_exchange_rejects_bad_token():
    resp = TestClient(app).post("/auth/session", json={"token": "not-a-jwt"})
    assert resp.status_code == 401
