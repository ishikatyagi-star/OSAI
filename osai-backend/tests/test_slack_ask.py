"""Slack /ask slash command: tokened URL, background answer delivery."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _mint() -> str:
    resp = client.post("/settings/slack-ask-token")
    assert resp.status_code == 200
    return resp.json()["token"]


def test_mint_ask_and_revoke():
    token = _mint()
    assert token.startswith("osas_")

    fake = MagicMock()
    fake.answer = "Priya owns infra."
    fake.citations = []
    with (
        patch("agent.orchestrator.run_ask", new=AsyncMock(return_value=fake)),
        patch("api.routes.slack_ask.httpx.post") as posted,
    ):
        r = TestClient(app).post(
            f"/slack/ask/{token}",
            data={"text": "who owns infra?", "response_url": "https://hooks.slack.test/x"},
        )
        assert r.status_code == 200
        assert "Looking into" in r.json()["text"]
        # Background task ran during TestClient response teardown.
        assert posted.call_args.kwargs["json"]["text"].startswith("Priya owns infra.")

    # Empty question → usage hint, no background work.
    r = TestClient(app).post(f"/slack/ask/{token}", data={"text": " "})
    assert "Ask me something" in r.json()["text"]

    # Bad token → 401; revoke kills the URL.
    assert TestClient(app).post("/slack/ask/osas_wrong", data={"text": "x"}).status_code == 401
    assert client.delete("/settings/slack-ask-token").json()["revoked"] is True
    assert TestClient(app).post(f"/slack/ask/{token}", data={"text": "x"}).status_code == 401
