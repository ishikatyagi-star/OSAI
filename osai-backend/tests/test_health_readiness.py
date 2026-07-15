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
        "semantic_embeddings",
        "embedding_model",
        "google_oauth",
        "email_login",
    ):
        assert key in caps, key
    assert "manual" in caps["automation_cadences"]
    # Recurring cadences may only be offered when the scheduler works.
    recurring = set(caps["automation_cadences"]) - {"manual"}
    assert bool(recurring) == bool(caps["scheduler"])
    # Retrieval quality must be honest: the hash fallback is reported as such,
    # never dressed up as a real embedding model.
    assert (caps["embedding_model"] == "hash-fallback") != caps["semantic_embeddings"]


def test_scheduler_reports_false_without_a_live_worker(monkeypatch):
    """A reachable Redis broker is not enough: on the free tier Redis is up but
    no worker is deployed, so a recurring schedule would be accepted and never
    run. scheduler must reflect a live worker, and no worker means no recurring
    cadences offered — otherwise the UI promises a cadence that silently never
    fires."""
    # A broker with no worker consuming: control.ping() returns no replies.
    monkeypatch.setattr(
        "workers.celery_app.celery_app.control.ping",
        lambda timeout=1.0: [],
    )
    caps = client.get("/capabilities").json()
    assert caps["scheduler"] is False
    assert caps["automation_cadences"] == ["manual"]

    # A responsive worker: at least one ping reply.
    monkeypatch.setattr(
        "workers.celery_app.celery_app.control.ping",
        lambda timeout=1.0: [{"worker@host": {"ok": "pong"}}],
    )
    caps = client.get("/capabilities").json()
    assert caps["scheduler"] is True
    assert "daily" in caps["automation_cadences"]


def test_scheduler_false_when_broker_ping_raises(monkeypatch):
    """A dead/unreachable broker must fail closed to no scheduler, not error."""
    def _boom(timeout=1.0):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr("workers.celery_app.celery_app.control.ping", _boom)
    assert client.get("/capabilities").json()["scheduler"] is False
