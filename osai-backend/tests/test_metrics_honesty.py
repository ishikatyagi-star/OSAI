"""Metrics must not turn a failure into a plausible-looking answer (SHE-6 P1).

"0 documents, 0 members" is not an error message: it reads as "your workspace is
empty", i.e. data loss. The free-tier database pauses when idle, so an outage is
routine — and it must never be indistinguishable from an empty workspace.

Same for sync history, which used to invent a "seed-sync-notion / not_started"
run both when the database was down and when the org had simply never synced.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from api.main import app

client = TestClient(app)


def _db_down(*_a, **_k):
    raise OperationalError("SELECT 1", {}, Exception("database is paused"))


# --- Dashboard metrics -------------------------------------------------------


def test_database_failure_is_not_reported_as_zeros(monkeypatch):
    """The headline: an outage must not render as an empty workspace."""
    import api.routes.dashboard as dashboard

    monkeypatch.setattr(dashboard, "_metrics", _db_down)
    resp = client.get("/dashboard/metrics")

    assert resp.status_code == 503
    body = resp.json()
    # Crucially, not a 200 carrying total_documents: 0.
    assert "total_documents" not in body
    assert "not lost" in body["detail"]


def test_real_metrics_answer_200_with_freshness():
    resp = client.get("/dashboard/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "total_documents" in body
    # SHE-6 P1: "Metrics response includes as_of".
    assert body["as_of"], "metrics must say when they were true"


def test_a_genuinely_empty_workspace_still_answers_zero(monkeypatch):
    """An empty org is a real answer, not an error — only failures may 503."""
    import api.routes.dashboard as dashboard

    empty = {
        "total_documents": 0,
        "documents_by_connector": {},
        "documents_by_tier": {},
        "connectors_connected": 0,
        "sync_runs_total": 0,
        "sync_runs_succeeded": 0,
        "last_sync_at": None,
        "members": 0,
        "departments": 0,
        "automations": 0,
    }
    monkeypatch.setattr(dashboard, "_metrics", lambda *_a, **_k: empty)
    resp = client.get("/dashboard/metrics")

    assert resp.status_code == 200
    assert resp.json()["total_documents"] == 0
    assert resp.json()["as_of"]


# --- Sync history ------------------------------------------------------------


def test_sync_history_failure_does_not_invent_a_run(monkeypatch):
    import api.routes.sync_runs as sync_runs

    monkeypatch.setattr(sync_runs, "list_db_sync_runs", _db_down)
    resp = client.get("/sync-runs")

    assert resp.status_code == 503
    assert "not lost" in resp.json()["detail"]


def test_a_workspace_that_never_synced_shows_nothing(monkeypatch):
    """It used to show a fabricated Notion run that had never happened."""
    import api.routes.sync_runs as sync_runs

    monkeypatch.setattr(sync_runs, "list_db_sync_runs", lambda *_a, **_k: [])
    resp = client.get("/sync-runs")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.parametrize("path", ["/dashboard/metrics", "/sync-runs"])
def test_no_endpoint_fabricates_seed_data(monkeypatch, path):
    """Guard the specific fixture that used to leak into real workspaces."""
    import api.routes.sync_runs as sync_runs

    monkeypatch.setattr(sync_runs, "list_db_sync_runs", lambda *_a, **_k: [])
    assert "seed-sync-notion" not in client.get(path).text
