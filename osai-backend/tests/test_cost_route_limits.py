from __future__ import annotations

import hashlib
import hmac
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import jwt
import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import api.ratelimit as limiter
from api.main import app
from api.ratelimit import (
    EVAL_RUN_BUDGET,
    INGEST_START_BUDGET,
    INTERACTIVE_AI_BUDGET,
    OAUTH_START_BUDGET,
    PROVIDER_ACTION_BUDGET,
    SQL_EXECUTE_BUDGET,
    SQL_PLAN_BUDGET,
    SQL_SCHEMA_BUDGET,
    WORKFLOW_RUN_BUDGET,
)
from api.routes import agent, composio, slack_ask
from config import settings

client = TestClient(app)


def _request(*, path: str = "/cost", client_ip: str = "198.51.100.10") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": (client_ip, 12345),
            "server": ("testserver", 80),
        }
    )


def _route_budgets(method: str, path: str) -> set[tuple[int, int]]:
    def walk(routes):
        for route in routes:
            nested = getattr(route, "original_router", None)
            if nested is None:
                yield route
            else:
                yield from walk(nested.routes)

    route = next(
        route
        for route in walk(app.routes)
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set())
    )
    return {
        budget
        for dependency in route.dependant.dependencies
        if (budget := getattr(dependency.call, "rate_limit_budget", None)) is not None
    }


def _token(org_id: str) -> str:
    return jwt.encode(
        {"sub": f"user-{org_id}", "org_id": org_id, "role": "admin"},
        settings.jwt_secret,
        algorithm="HS256",
    )


def test_every_expensive_session_route_declares_its_cost_budget():
    expected = {
        ("POST", "/ask"): INTERACTIVE_AI_BUDGET,
        ("POST", "/ask/actions/{action_id}/confirm"): PROVIDER_ACTION_BUDGET,
        ("POST", "/ask/actions/{action_id}/dismiss"): PROVIDER_ACTION_BUDGET,
        ("POST", "/automations/{automation_id}/run"): WORKFLOW_RUN_BUDGET,
        ("POST", "/automations/{automation_id}/trigger"): PROVIDER_ACTION_BUDGET,
        ("POST", "/documents/upload"): INGEST_START_BUDGET,
        ("POST", "/evals"): EVAL_RUN_BUDGET,
        ("POST", "/integrations/composio/connect/{toolkit}"): OAUTH_START_BUDGET,
        ("GET", "/integrations/composio/callback"): OAUTH_START_BUDGET,
        ("POST", "/integrations/composio/sync"): INGEST_START_BUDGET,
        ("POST", "/integrations/composio/disconnect/{toolkit}"): PROVIDER_ACTION_BUDGET,
        ("POST", "/integrations/composio/{toolkit}/ingest"): INGEST_START_BUDGET,
        ("POST", "/integrations/{connector_key}/sync"): INGEST_START_BUDGET,
        ("POST", "/search"): INTERACTIVE_AI_BUDGET,
        ("POST", "/sql/sources"): PROVIDER_ACTION_BUDGET,
        ("GET", "/sql/sources/{source_id}/schema"): SQL_SCHEMA_BUDGET,
        ("POST", "/sql/plan"): SQL_PLAN_BUDGET,
        ("POST", "/sql/execute"): SQL_EXECUTE_BUDGET,
        ("POST", "/workflows"): WORKFLOW_RUN_BUDGET,
        (
            "POST",
            "/workflows/{run_id}/action-items/{item_id}/approve",
        ): PROVIDER_ACTION_BUDGET,
    }

    for route, budget in expected.items():
        assert budget in _route_budgets(*route), route


@pytest.mark.anyio
async def test_verified_tenants_and_anonymous_clients_have_separate_buckets(monkeypatch):
    monkeypatch.setattr(settings, "env", "local")
    request = _request()

    with pytest.raises(ValueError):
        await limiter.enforce_rate_limit(
            request, max_calls=1, window_seconds=60, verified_tenant_id=" "
        )

    await limiter.enforce_rate_limit(
        request, max_calls=1, window_seconds=60, verified_tenant_id="org-a"
    )
    with pytest.raises(HTTPException) as exhausted:
        await limiter.enforce_rate_limit(
            request, max_calls=1, window_seconds=60, verified_tenant_id="org-a"
        )
    assert exhausted.value.status_code == 429
    await limiter.enforce_rate_limit(
        request, max_calls=1, window_seconds=60, verified_tenant_id="org-b"
    )
    await limiter.enforce_rate_limit(
        _request(client_ip="198.51.100.11"),
        max_calls=1,
        window_seconds=60,
        verified_tenant_id="org-a",
    )

    limiter._HITS.clear()
    await limiter.enforce_rate_limit(request, max_calls=1, window_seconds=60)
    with pytest.raises(HTTPException) as anonymous_exhausted:
        await limiter.enforce_rate_limit(request, max_calls=1, window_seconds=60)
    assert anonymous_exhausted.value.status_code == 429
    await limiter.enforce_rate_limit(
        _request(client_ip="198.51.100.11"), max_calls=1, window_seconds=60
    )


def test_expensive_route_returns_stable_429_and_redis_failure_503(monkeypatch):
    run_ask = AsyncMock()
    monkeypatch.setattr(agent, "run_ask", run_ask)
    headers = {"Authorization": f"Bearer {_token('org-cost')}"}
    body = {"question": "Does this reach the model?"}

    monkeypatch.setattr(settings, "env", "local")
    monkeypatch.setattr(limiter, "_memory_allow", lambda *_args, **_kwargs: False)
    limited = client.post("/ask", headers=headers, json=body)
    assert limited.status_code == 429
    assert limited.json() == {"detail": limiter._LIMIT_DETAIL}
    run_ask.assert_not_awaited()

    async def unavailable(*_args, **_kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(limiter, "_redis_allow", unavailable)
    unavailable_response = client.post("/ask", headers=headers, json=body)
    assert unavailable_response.status_code == 503
    assert unavailable_response.json() == {"detail": limiter._UNAVAILABLE_DETAIL}
    run_ask.assert_not_awaited()


def test_cheap_reads_never_enter_the_limiter(monkeypatch):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("safe read entered the rate limiter")

    monkeypatch.setattr(limiter, "_memory_allow", should_not_run)
    for _ in range(25):
        assert client.get("/health/live").status_code == 200

    for method, path in (
        ("GET", "/evals"),
        ("GET", "/integrations"),
        ("GET", "/integrations/composio/connections"),
        ("GET", "/workflows"),
    ):
        assert not _route_budgets(method, path)


@pytest.mark.anyio
async def test_composio_callback_uses_only_the_signed_state_tenant(monkeypatch):
    enforce = AsyncMock()
    monkeypatch.setattr(composio, "enforce_rate_limit", enforce)
    state = composio._issue_oauth_state("org-callback", "admin-a", "googledrive")

    await composio._limit_oauth_callback(
        _request(path="/integrations/composio/callback"), state=state
    )
    assert enforce.await_args.kwargs["verified_tenant_id"] == "org-callback"

    enforce.reset_mock()
    await composio._limit_oauth_callback(
        _request(path="/integrations/composio/callback"), state=state + "tampered"
    )
    enforce.assert_not_awaited()


@pytest.mark.anyio
async def test_slack_ask_uses_the_token_verified_tenant(monkeypatch):
    signing_secret = "slack-cost-limit-test-secret"
    monkeypatch.setattr(settings, "slack_signing_secret", signing_secret)
    token = "verified-route-token"
    raw = urlencode({"text": "costly question"}).encode()
    timestamp = str(int(time.time()))
    signature = (
        "v0="
        + hmac.new(
            signing_secret.encode(),
            b"v0:" + timestamp.encode() + b":" + raw,
            hashlib.sha256,
        ).hexdigest()
    )
    enforce = AsyncMock(side_effect=HTTPException(status_code=429, detail="limited"))
    monkeypatch.setattr(slack_ask, "enforce_rate_limit", enforce)

    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": f"/slack/ask/{token}",
            "raw_path": f"/slack/ask/{token}".encode(),
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(raw)).encode()),
                (b"x-slack-request-timestamp", timestamp.encode()),
                (b"x-slack-signature", signature.encode()),
            ],
            "client": ("198.51.100.10", 12345),
            "server": ("testserver", 80),
        },
        receive,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id="org-slack")

    with pytest.raises(HTTPException) as limited:
        await slack_ask.slack_ask(token, BackgroundTasks(), db, request)
    assert limited.value.status_code == 429
    assert enforce.await_args.kwargs["verified_tenant_id"] == "org-slack"
