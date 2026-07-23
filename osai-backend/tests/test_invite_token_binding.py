"""Invite acceptance is bound to the exact opaque link used for OAuth."""

from __future__ import annotations

from datetime import timedelta
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes import auth, team
from config import settings
from db.models import Base, Invite, Org, User, now_utc
from db.repositories import (
    INVITE_TTL,
    accept_invite_by_token,
    create_invite,
    revoke_invite,
)


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def google_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_oauth_client_id", "google-client")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "google-secret")
    monkeypatch.setattr(
        settings,
        "google_oauth_redirect_uri",
        "https://api.example.test/auth/google/callback",
    )
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.test")


@pytest.fixture
def auth_client() -> TestClient:
    app = FastAPI()
    app.include_router(auth.router)
    return TestClient(app)


def _add_orgs(db: Session, *org_ids: str) -> None:
    db.add_all([Org(id=org_id, name=org_id) for org_id in org_ids])
    db.commit()


def _callback_request(state_cookie: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/auth/google/callback",
            "raw_path": b"/auth/google/callback",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (
                    b"cookie",
                    f"{auth._OAUTH_STATE_COOKIE}={state_cookie}".encode("ascii"),
                )
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("api.example.test", 443),
        }
    )


def _begin_oauth(client: TestClient, invite_token: str | None) -> tuple[str, str, str]:
    if invite_token is None:
        response = client.get("/auth/google/start", follow_redirects=False)
        assert response.status_code == 307
    else:
        response = client.post(
            "/auth/google/start",
            data={"invite": invite_token},
            follow_redirects=False,
        )
        assert response.status_code == 303
    google_url = response.headers["location"]
    nonce = parse_qs(urlsplit(google_url).query)["state"][0]
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    state_cookie = cookies[auth._OAUTH_STATE_COOKIE].value
    return nonce, state_cookie, google_url


def _mock_google_identity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    email: str,
    name: str = "Invitee",
) -> None:
    monkeypatch.setattr(
        auth,
        "_exchange_code",
        AsyncMock(return_value={"id_token": "verified-id-token"}),
    )
    monkeypatch.setattr(
        auth,
        "_verify_id_token",
        lambda _token: {"email": email, "name": name, "email_verified": True},
    )


def test_invite_link_keeps_the_opaque_token_in_the_fragment(
    google_enabled: None,
) -> None:
    token = "opaque_token-1234567890"

    link = team._invite_link(token)

    assert link == f"https://app.example.test/login#invite={token}"
    assert "?invite=" not in link


def test_invite_post_binds_token_without_putting_it_in_a_url(
    google_enabled: None,
    auth_client: TestClient,
) -> None:
    token = "opaque_token-1234567890"

    nonce, state_cookie, google_url = _begin_oauth(auth_client, token)

    payload = auth._decode_google_oauth_state(state_cookie)
    assert payload["nonce"] == nonce
    assert payload["invite_token"] == token
    assert token not in google_url


@pytest.mark.parametrize("token", ["a" * 16, "Z" * 256])
def test_invite_post_accepts_token_boundaries_and_content_type_charset(
    google_enabled: None,
    auth_client: TestClient,
    token: str,
) -> None:
    response = auth_client.post(
        "/auth/google/start",
        content=f"invite={token}",
        headers={"content-type": "application/x-www-form-urlencoded; charset=UTF-8"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    payload = auth._decode_google_oauth_state(cookies[auth._OAUTH_STATE_COOKIE].value)
    assert payload["invite_token"] == token


@pytest.mark.parametrize(
    ("body", "content_type", "expected_status"),
    [
        ("invite=too-short", "application/x-www-form-urlencoded", 400),
        (
            "invite=opaque_token-1234567890&invite=opaque_token-1234567890",
            "application/x-www-form-urlencoded",
            400,
        ),
        (
            "unknown=opaque_token-1234567890",
            "application/x-www-form-urlencoded",
            400,
        ),
        ("", "application/x-www-form-urlencoded", 400),
        ("invite", "application/x-www-form-urlencoded", 400),
        ("invite=", "application/x-www-form-urlencoded", 400),
        ("invite=%FF", "application/x-www-form-urlencoded", 400),
        ("invite=" + "a" * 257, "application/x-www-form-urlencoded", 400),
        ("invite=opaque%21token-1234567890", "application/x-www-form-urlencoded", 400),
        ("invite=opaque_token-1234567890", "application/json", 415),
        ("invite=opaque_token-1234567890", "multipart/form-data", 415),
        ("invite=opaque_token-1234567890", None, 415),
        ("invite=" + "a" * 506, "application/x-www-form-urlencoded", 413),
    ],
)
def test_invite_post_rejects_invalid_content_type_size_and_shape(
    google_enabled: None,
    auth_client: TestClient,
    body: str,
    content_type: str | None,
    expected_status: int,
) -> None:
    headers = {"content-type": content_type} if content_type else {}

    response = auth_client.post(
        "/auth/google/start",
        content=body,
        headers=headers,
        follow_redirects=False,
    )

    assert response.status_code == expected_status
    assert auth._OAUTH_STATE_COOKIE not in response.cookies


@pytest.mark.parametrize(
    ("content_length", "expected_status"),
    [("not-a-number", 400), ("-1", 400), ("513", 413)],
)
def test_invite_post_rejects_invalid_declared_body_lengths(
    google_enabled: None,
    auth_client: TestClient,
    content_length: str,
    expected_status: int,
) -> None:
    response = auth_client.post(
        "/auth/google/start",
        content="invite=opaque_token-1234567890",
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "content-length": content_length,
        },
        follow_redirects=False,
    )

    assert response.status_code == expected_status
    assert auth._OAUTH_STATE_COOKIE not in response.cookies


def test_invite_post_enforces_stream_size_when_declared_length_is_small(
    google_enabled: None,
    auth_client: TestClient,
) -> None:
    response = auth_client.post(
        "/auth/google/start",
        content="invite=" + "a" * 506,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "content-length": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 413
    assert auth._OAUTH_STATE_COOKIE not in response.cookies


def test_get_start_rejects_query_data_but_preserves_ordinary_sign_in(
    google_enabled: None,
    auth_client: TestClient,
) -> None:
    token = "opaque_token-1234567890"

    rejected = auth_client.get(f"/auth/google/start?invite={token}", follow_redirects=False)
    rejected_post = auth_client.post(
        f"/auth/google/start?invite={token}",
        data={"invite": token},
        follow_redirects=False,
    )
    nonce, state_cookie, google_url = _begin_oauth(auth_client, None)

    assert rejected.status_code == 400
    assert auth._OAUTH_STATE_COOKIE not in rejected.cookies
    assert rejected_post.status_code == 400
    assert auth._OAUTH_STATE_COOKIE not in rejected_post.cookies
    payload = auth._decode_google_oauth_state(state_cookie)
    assert payload["nonce"] == nonce
    assert "invite_token" not in payload
    assert token not in google_url


@pytest.mark.anyio
async def test_oauth_accepts_the_followed_invite_not_a_newer_cross_org_invite(
    db: Session,
    google_enabled: None,
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_orgs(db, "org-followed", "org-newer")
    followed = create_invite(db, "org-followed", "Person@Example.Test")
    newer = create_invite(db, "org-newer", "person@example.test", role="admin")
    _mock_google_identity(monkeypatch, email=" PERSON@example.TEST ")

    nonce, state_cookie, google_url = _begin_oauth(auth_client, followed.token)
    assert followed.token not in google_url
    response = await auth.google_callback(
        _callback_request(state_cookie), db, code="google-code", state=nonce
    )

    user = db.scalar(select(User).where(User.email == "person@example.test"))
    assert user is not None
    assert user.org_id == "org-followed"
    assert db.get(Invite, followed.id).status == "accepted"
    assert db.get(Invite, newer.id).status == "pending"
    assert followed.token not in response.headers["location"]


def test_invite_token_rejects_wrong_email_revoked_expired_and_replay(db: Session) -> None:
    _add_orgs(db, "org-a", "org-b")

    wrong = create_invite(db, "org-a", "wrong@example.test")
    assert accept_invite_by_token(db, "not-the-followed-token", wrong.email, "Wrong") is None
    assert db.get(Invite, wrong.id).status == "pending"

    mismatch = create_invite(db, "org-a", "target@example.test")
    assert accept_invite_by_token(db, mismatch.token, "other@example.test", "Other") is None
    assert db.get(Invite, mismatch.id).status == "pending"

    revoked = create_invite(db, "org-a", "revoked@example.test")
    assert revoke_invite(db, "org-a", revoked.id) is True
    assert accept_invite_by_token(db, revoked.token, revoked.email, "Revoked") is None

    expired = create_invite(db, "org-b", "expired@example.test")
    expired.created_at = now_utc() - INVITE_TTL - timedelta(seconds=1)
    db.commit()
    assert accept_invite_by_token(db, expired.token, expired.email, "Expired") is None
    assert db.get(Invite, expired.id).status == "pending"

    replayed = create_invite(db, "org-b", "replay@example.test")
    accepted = accept_invite_by_token(db, replayed.token, "REPLAY@example.test", "Replay")
    assert accepted is not None
    assert accepted.org_id == "org-b"
    assert accept_invite_by_token(db, replayed.token, replayed.email, "Replay Again") is None
    assert db.get(Invite, replayed.id).status == "accepted"


def test_reissuing_an_invite_rotates_the_token_and_invalidates_the_old_link(
    db: Session,
) -> None:
    _add_orgs(db, "org-a")
    first = create_invite(db, "org-a", "refresh@example.test")
    old_token = first.token

    refreshed = create_invite(db, "org-a", "REFRESH@example.test", role="admin")

    assert refreshed.id == first.id
    assert refreshed.token != old_token
    assert accept_invite_by_token(db, old_token, refreshed.email, "Old Link") is None
    user = accept_invite_by_token(db, refreshed.token, refreshed.email, "Fresh Link")
    assert user is not None
    assert user.role == "admin"


@pytest.mark.anyio
async def test_invalid_invite_flow_does_not_fall_back_to_workspace_provisioning(
    db: Session,
    google_enabled: None,
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_google_identity(monkeypatch, email="new@example.test")
    nonce, state_cookie, _ = _begin_oauth(auth_client, "wrong-but-wellformed-token")

    with pytest.raises(HTTPException) as error:
        await auth.google_callback(
            _callback_request(state_cookie), db, code="google-code", state=nonce
        )

    assert error.value.status_code == 400
    assert db.scalar(select(User).where(User.email == "new@example.test")) is None
    assert db.scalar(select(Org.id)) is None


@pytest.mark.anyio
async def test_ordinary_non_invite_google_sign_in_still_provisions_a_workspace(
    db: Session,
    google_enabled: None,
    auth_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_google_identity(monkeypatch, email="OWNER@Example.Test", name="Owner")
    nonce, state_cookie, _ = _begin_oauth(auth_client, None)

    response = await auth.google_callback(
        _callback_request(state_cookie), db, code="google-code", state=nonce
    )

    user = db.scalar(select(User).where(User.email == "owner@example.test"))
    assert user is not None
    assert user.role == "admin"
    assert db.get(Org, user.org_id) is not None
    assert response.headers["location"].startswith("https://app.example.test/auth/callback#")
