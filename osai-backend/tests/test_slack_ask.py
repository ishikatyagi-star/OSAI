"""Slack /ask boundary: admin setup, request auth, actor mapping, and egress."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import jwt
import pytest
from fastapi.testclient import TestClient

from api.main import app
from config import settings
from db.models import Org, SlackRequestUse, User
from db.session import SessionLocal, get_org_id, require_admin, require_writable_org

client = TestClient(app)
_SIGNING_SECRET = "slack-signing-secret-for-tests"
_SLACK_TEST_ORG_ID = "slack-test-org"
_SLACK_TEST_USER_ID = "slack-test-user"


def _normal_citation(title: str = "Workspace source") -> SimpleNamespace:
    return SimpleNamespace(source_record_title=title, data_tier="normal")


@pytest.fixture(autouse=True)
def _slack_settings(monkeypatch):
    monkeypatch.setattr(settings, "slack_signing_secret", _SIGNING_SECRET)
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-test")


@pytest.fixture(autouse=True)
def _slack_workspace(_override_auth):
    """Exercise normal Slack behavior in a real writable test workspace.

    The shared demo organization is deliberately read-only, including tokened
    Slack requests. These functional tests need a separate tenant so a passing
    result cannot weaken or bypass that production boundary.
    """
    with SessionLocal() as db:
        if db.get(Org, _SLACK_TEST_ORG_ID) is None:
            db.add(Org(id=_SLACK_TEST_ORG_ID, name="Slack test workspace"))
        if db.get(User, _SLACK_TEST_USER_ID) is None:
            db.add(
                User(
                    id=_SLACK_TEST_USER_ID,
                    org_id=_SLACK_TEST_ORG_ID,
                    email="slack-user@example.test",
                    display_name="Slack Test User",
                    role="admin",
                    token_version=0,
                )
            )
        db.commit()

    saved = {
        dependency: app.dependency_overrides.get(dependency)
        for dependency in (get_org_id, require_admin, require_writable_org)
    }
    app.dependency_overrides[get_org_id] = lambda: _SLACK_TEST_ORG_ID
    app.dependency_overrides[require_writable_org] = lambda: _SLACK_TEST_ORG_ID
    app.dependency_overrides[require_admin] = lambda: {
        "org_id": _SLACK_TEST_ORG_ID,
        "role": "admin",
        "sub": _SLACK_TEST_USER_ID,
    }
    yield
    for dependency, override in saved.items():
        if override is None:
            app.dependency_overrides.pop(dependency, None)
        else:
            app.dependency_overrides[dependency] = override


def _mint() -> str:
    resp = client.post("/settings/slack-ask-token")
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _signed_post(
    path: str,
    fields: dict[str, str],
    *,
    timestamp: int | None = None,
    signature: str | None = None,
):
    raw = urlencode(fields).encode()
    timestamp = timestamp if timestamp is not None else int(time.time())
    base = b"v0:" + str(timestamp).encode() + b":" + raw
    valid_signature = "v0=" + hmac.new(_SIGNING_SECRET.encode(), base, hashlib.sha256).hexdigest()
    return TestClient(app).post(
        path,
        content=raw,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "x-slack-request-timestamp": str(timestamp),
            "x-slack-signature": signature or valid_signature,
        },
    )


def _slack_user() -> User:
    with SessionLocal() as db:
        user = db.get(User, _SLACK_TEST_USER_ID)
        assert user is not None
        db.expunge(user)
        return user


def test_mint_ask_and_revoke_maps_mixed_case_email_to_explicit_user_context():
    token = _mint()
    assert token.startswith("osas_")
    user = _slack_user()

    fake = MagicMock()
    fake.answer = "Priya owns infra."
    fake.citations = [_normal_citation("Ownership map")]
    ask = AsyncMock(return_value=fake)
    with (
        patch("agent.orchestrator.run_ask", new=ask),
        patch(
            "api.routes.slack_ask._slack_user_email",
            new=AsyncMock(return_value=f"  {user.email.upper()}  "),
        ),
        patch("api.routes.slack_ask.httpx.post") as posted,
    ):
        response = _signed_post(
            f"/slack/ask/{token}",
            {
                "text": "who owns infra?",
                "user_id": "U123",
                "response_url": "https://hooks.slack.com/commands/T/B/secret",
            },
        )
    assert response.status_code == 200
    assert "Looking into" in response.json()["text"]
    assert ask.await_args.kwargs["user_id"] == user.id
    assert f"user:{user.id}" in ask.await_args.kwargs["requester_permissions"]
    assert ask.await_args.kwargs["requester_tier"] in {"normal", "amber", "red"}
    assert posted.call_args.kwargs["json"]["text"].startswith("Priya owns infra.")
    assert posted.call_args.kwargs["json"]["response_type"] == "ephemeral"
    assert posted.call_args.kwargs["follow_redirects"] is False

    empty = _signed_post(f"/slack/ask/{token}", {"text": " "})
    assert "Ask me something" in empty.json()["text"]
    assert _signed_post("/slack/ask/osas_wrong", {"text": "x"}).status_code == 401
    assert client.delete("/settings/slack-ask-token").json()["revoked"] is True
    assert _signed_post(f"/slack/ask/{token}", {"text": "x"}).status_code == 401


def test_slack_signature_and_timestamp_fail_closed():
    token = _mint()
    unsigned = client.post(f"/slack/ask/{token}", data={"text": "x"})
    assert unsigned.status_code == 401
    stale = _signed_post(
        f"/slack/ask/{token}",
        {"text": "x"},
        timestamp=int(time.time()) - 301,
    )
    assert stale.status_code == 401
    bad = _signed_post(
        f"/slack/ask/{token}",
        {"text": "x"},
        signature="v0=" + "0" * 64,
    )
    assert bad.status_code == 401


def test_slack_request_is_consumed_once():
    token = _mint()
    timestamp = int(time.time()) + 299
    fields = {
        "text": "deduplicate this request",
        "user_id": "U123",
    }
    fake = MagicMock(answer="Once.", citations=[_normal_citation()])
    ask = AsyncMock(return_value=fake)
    with (
        patch("agent.orchestrator.run_ask", new=ask),
        patch(
            "api.routes.slack_ask._slack_user_email",
            new=AsyncMock(return_value=_slack_user().email),
        ),
    ):
        first = _signed_post(f"/slack/ask/{token}", fields, timestamp=timestamp)
        replay = _signed_post(f"/slack/ask/{token}", fields, timestamp=timestamp)

    assert first.status_code == 200
    assert first.json()["text"].startswith("Once.")
    assert replay.status_code == 200
    assert "already accepted" in replay.json()["text"]
    ask.assert_awaited_once()
    request_hash = hashlib.sha256(
        str(timestamp).encode() + b":" + urlencode(fields).encode()
    ).hexdigest()
    with SessionLocal() as db:
        expires_at = db.get(SlackRequestUse, request_hash).expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    assert expires_at > datetime.now(UTC) + timedelta(minutes=9)


def test_background_slack_request_is_consumed_once():
    token = _mint()
    timestamp = int(time.time())
    fields = {
        "text": "deduplicate this background request",
        "user_id": "U123",
        "response_url": "https://hooks.slack.com/commands/T/B/replay",
    }
    ask = AsyncMock(return_value=MagicMock(answer="Once.", citations=[_normal_citation()]))
    with (
        patch("agent.orchestrator.run_ask", new=ask),
        patch(
            "api.routes.slack_ask._slack_user_email",
            new=AsyncMock(return_value=_slack_user().email),
        ),
        patch("api.routes.slack_ask.httpx.post") as posted,
    ):
        first = _signed_post(f"/slack/ask/{token}", fields, timestamp=timestamp)
        replay = _signed_post(f"/slack/ask/{token}", fields, timestamp=timestamp)

    assert first.status_code == replay.status_code == 200
    ask.assert_awaited_once()
    posted.assert_called_once()


def test_slack_answer_without_citation_provenance_is_withheld():
    token = _mint()
    ask = AsyncMock(return_value=MagicMock(answer="Unattributed secret.", citations=[]))
    with (
        patch("agent.orchestrator.run_ask", new=ask),
        patch(
            "api.routes.slack_ask._slack_user_email",
            new=AsyncMock(return_value=_slack_user().email),
        ),
    ):
        response = _signed_post(
            f"/slack/ask/{token}",
            {"text": "unattributed answer", "user_id": "U123"},
        )
    assert response.status_code == 200
    assert "withheld" in response.json()["text"].lower()
    assert "Unattributed secret" not in response.json()["text"]


def test_slack_request_body_is_bounded_before_processing():
    token = _mint()
    oversized = _signed_post(f"/slack/ask/{token}", {"text": "x" * (64 * 1024)})
    assert oversized.status_code == 413


def test_slack_endpoint_fails_closed_without_signing_secret(monkeypatch):
    monkeypatch.setattr(settings, "slack_signing_secret", None)
    assert client.post("/settings/slack-ask-token").status_code == 503
    assert client.post("/slack/ask/anything", data={"text": "x"}).status_code == 503


def test_slack_token_mint_requires_user_mapping_configuration(monkeypatch):
    monkeypatch.setattr(settings, "slack_bot_token", None)
    assert client.post("/settings/slack-ask-token").status_code == 503


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.slack.com/commands/T/B/x",
        "https://hooks.slack.com.evil.test/commands/T/B/x",
        "https://user@hooks.slack.com/commands/T/B/x",
        "https://hooks.slack.com:8443/commands/T/B/x",
        "https://hooks.slack.com/services/T/B/x",
        "https://127.0.0.1/commands/T/B/x",
    ],
)
def test_slack_response_url_rejects_non_slack_destinations(url):
    from api.routes.slack_ask import _is_allowed_response_url

    assert _is_allowed_response_url(url) is False


def test_unmapped_slack_user_fails_before_ask():
    token = _mint()
    ask = AsyncMock()
    with (
        patch(
            "api.routes.slack_ask._slack_user_email",
            new=AsyncMock(return_value="not-a-member@example.test"),
        ),
        patch("agent.orchestrator.run_ask", new=ask),
    ):
        response = _signed_post(
            f"/slack/ask/{token}",
            {"text": "private question", "user_id": "U999"},
        )
    assert response.status_code == 403
    ask.assert_not_awaited()


def test_unmapped_background_request_posts_failure_without_ask():
    token = _mint()
    ask = AsyncMock()
    with (
        patch(
            "api.routes.slack_ask._slack_user_email",
            new=AsyncMock(return_value="not-a-member@example.test"),
        ),
        patch("agent.orchestrator.run_ask", new=ask),
        patch("api.routes.slack_ask.httpx.post") as posted,
    ):
        response = _signed_post(
            f"/slack/ask/{token}",
            {
                "text": "private question",
                "user_id": "U999",
                "response_url": "https://hooks.slack.com/commands/T/B/secret",
            },
        )
    assert response.status_code == 200
    ask.assert_not_awaited()
    assert "not linked" in posted.call_args.kwargs["json"]["text"]


def test_non_slack_response_url_is_rejected_before_ask():
    token = _mint()
    ask = AsyncMock()
    with (
        patch(
            "api.routes.slack_ask._slack_user_email",
            new=AsyncMock(return_value=_slack_user().email),
        ),
        patch("agent.orchestrator.run_ask", new=ask),
    ):
        response = _signed_post(
            f"/slack/ask/{token}",
            {
                "text": "send this internally",
                "user_id": "U123",
                "response_url": "https://127.0.0.1/commands/T/B/x",
            },
        )
    assert response.status_code == 422
    ask.assert_not_awaited()


@pytest.fixture
def _real_admin_gate():
    saved = {
        dependency: app.dependency_overrides.pop(dependency, None)
        for dependency in (require_admin, require_writable_org)
    }
    yield
    for dependency, override in saved.items():
        if override is not None:
            app.dependency_overrides[dependency] = override


def _user_token(org_id: str, role: str) -> tuple[str, str]:
    user_id = f"user-{uuid.uuid4()}"
    with SessionLocal() as db:
        if db.get(Org, org_id) is None:
            db.add(Org(id=org_id, name=org_id))
        user = User(
            id=user_id,
            org_id=org_id,
            email=f"{user_id}@example.test",
            display_name=user_id,
            role=role,
            token_version=0,
        )
        db.add(user)
        db.commit()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": user_id,
            "org_id": org_id,
            "role": role,
            "tv": 0,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return user_id, token


def test_slack_token_management_requires_a_current_admin(_real_admin_gate):
    org_id = f"org-{uuid.uuid4()}"
    stale_id, stale_admin_token = _user_token(org_id, "admin")
    _, current_admin_token = _user_token(org_id, "admin")
    _, member_token = _user_token(org_id, "member")
    with SessionLocal() as db:
        db.get(User, stale_id).role = "member"
        db.commit()

    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    assert (
        client.post("/settings/slack-ask-token", headers=auth(stale_admin_token)).status_code == 403
    )
    assert client.post("/settings/slack-ask-token", headers=auth(member_token)).status_code == 403
    assert (
        client.post("/settings/slack-ask-token", headers=auth(current_admin_token)).status_code
        == 200
    )
    assert client.delete("/settings/slack-ask-token", headers=auth(member_token)).status_code == 403
    assert (
        client.delete("/settings/slack-ask-token", headers=auth(current_admin_token)).status_code
        == 200
    )
