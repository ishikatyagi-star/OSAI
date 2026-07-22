"""Operational endpoints: client-error intake and the automations cron hook."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from config import settings


def test_client_error_intake_accepts_and_caps_payload():
    client = TestClient(app)
    resp = client.post(
        "/internal/client-errors",
        json={"message": "boom", "stack": "x" * 10000, "path": "/ask", "source": "boundary"},
    )
    # Oversized stack is rejected by the schema cap rather than buffered.
    assert resp.status_code == 422

    resp = client.post(
        "/internal/client-errors",
        json={"message": "boom", "stack": "trace", "path": "/ask", "source": "global"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_run_due_is_404_without_configured_token():
    client = TestClient(app)
    assert settings.automations_cron_token is None
    resp = client.post("/internal/automations/run-due", headers={"X-Cron-Token": "guess"})
    assert resp.status_code == 404


def test_run_due_is_404_when_external_cron_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "automations_cron_token", "s3cret")
    monkeypatch.setattr(settings, "automations_cron_enabled", False)
    client = TestClient(app)

    resp = client.post("/internal/automations/run-due", headers={"X-Cron-Token": "s3cret"})
    assert resp.status_code == 404


def test_run_due_rejects_bad_token_and_accepts_good(monkeypatch):
    monkeypatch.setattr(settings, "automations_cron_token", "s3cret")
    monkeypatch.setattr(settings, "automations_cron_enabled", True)
    client = TestClient(app)

    resp = client.post("/internal/automations/run-due", headers={"X-Cron-Token": "wrong"})
    assert resp.status_code == 401

    async def fake_run_due():
        return {"ran": ["a1"], "failed": []}

    import agent.automation_runner as runner

    monkeypatch.setattr(runner, "run_due_automations", fake_run_due)
    resp = client.post("/internal/automations/run-due", headers={"X-Cron-Token": "s3cret"})
    assert resp.status_code == 200
    assert resp.json() == {"ran": ["a1"], "failed": []}
