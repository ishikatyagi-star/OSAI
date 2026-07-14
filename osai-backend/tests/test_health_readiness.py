"""Deployment-readiness endpoints: /health/live, /health/ready, /capabilities.

Readiness must fail closed (503) when storage/migrations are unusable, and
capabilities must describe what this deployment can actually run so the
frontend never offers a cadence or connector action that can't execute.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_live_is_dependency_free():
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


def test_ready_reports_dependency_checks():
    resp = client.get("/health/ready")
    body = resp.json()
    assert set(body["checks"]) == {"database", "vector_store"}
    # Against the provisioned test stack (CI service containers / local
    # docker-compose) everything must be usable.
    assert resp.status_code == 200, body
    assert body["status"] == "ready"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["database"]["revision"] == body["checks"]["database"]["expected"]
    assert body["checks"]["vector_store"]["ok"] is True


def test_ready_fails_closed_on_migration_drift(monkeypatch):
    """A DB that is reachable but not at this build's migration head is not
    ready — deploys must not report healthy over a half-migrated schema."""
    import api.routes.health as health

    monkeypatch.setattr(health, "_alembic_head", lambda: "not-the-deployed-revision")
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["ok"] is False


def test_ready_survives_a_hung_or_dead_dependency(monkeypatch):
    """Probe failures surface as a failed check, never as an exception/hang."""
    import api.routes.health as health

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(health, "_check_database", _boom)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert "RuntimeError" in resp.json()["checks"]["database"]["error"]


def test_capabilities_shape_and_cadence_consistency():
    resp = client.get("/capabilities")
    assert resp.status_code == 200
    caps = resp.json()
    for key in (
        "scheduler",
        "automation_cadences",
        "connectors",
        "sql_sources",
        "workflow_execution",
        "google_oauth",
        "email_login",
    ):
        assert key in caps, key
    assert "manual" in caps["automation_cadences"]
    # Recurring cadences may only be offered when the scheduler transport works.
    recurring = set(caps["automation_cadences"]) - {"manual"}
    assert bool(recurring) == bool(caps["scheduler"])
