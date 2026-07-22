"""Deployment-readiness endpoints: /health/live, /health/ready, /capabilities.

Readiness must fail closed (503) when storage/migrations are unusable, and
capabilities must describe what this deployment can actually run so the
frontend never offers a cadence or connector action that can't execute.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_live_is_dependency_free():
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


def test_ready_reports_dependency_checks(monkeypatch):
    import api.routes.health as health

    def _healthy_database():
        return {"ok": True, "revision": "head", "expected": "head"}

    async def _healthy_vector_store():
        return {"ok": True, "collection_present": True}

    async def _healthy_redis():
        return {"ok": True}

    monkeypatch.setattr(health, "_check_database", _healthy_database)
    monkeypatch.setattr(health, "_check_vector_store", _healthy_vector_store)
    monkeypatch.setattr(health, "_check_redis", _healthy_redis)
    resp = client.get("/health/ready")
    body = resp.json()
    assert set(body["checks"]) == {"database", "vector_store", "redis"}
    assert resp.status_code == 200, body
    assert body["status"] == "ready"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["database"]["revision"] == body["checks"]["database"]["expected"]
    assert body["checks"]["vector_store"]["ok"] is True
    assert body["checks"]["redis"]["ok"] is True


def test_ready_fails_closed_on_migration_drift(monkeypatch):
    """A DB that is reachable but not at this build's migration head is not
    ready — deploys must not report healthy over a half-migrated schema."""
    import api.routes.health as health

    def _drifted_database():
        return {"ok": False, "revision": "old", "expected": "head"}

    async def _healthy_dependency():
        return {"ok": True}

    monkeypatch.setattr(health, "_check_database", _drifted_database)
    monkeypatch.setattr(health, "_check_vector_store", _healthy_dependency)
    monkeypatch.setattr(health, "_check_redis", _healthy_dependency)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["ok"] is False


def test_ready_survives_a_hung_or_dead_dependency(monkeypatch):
    """Probe failures surface as a failed check, never as an exception/hang."""
    import api.routes.health as health

    def _boom():
        raise RuntimeError("postgresql://admin:secret@internal-db/prod")

    async def _healthy_dependency():
        return {"ok": True}

    monkeypatch.setattr(health, "_check_database", _boom)
    monkeypatch.setattr(health, "_check_vector_store", _healthy_dependency)
    monkeypatch.setattr(health, "_check_redis", _healthy_dependency)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["checks"]["database"]["error"] == "dependency_unavailable"
    assert "secret" not in resp.text


def test_ready_sanitizes_redis_eval_failure(monkeypatch):
    """Redis errors may contain credentials and must never enter the response."""
    import api.routes.health as health

    def _healthy_database():
        return {"ok": True}

    async def _healthy_vector_store():
        return {"ok": True}

    async def _boom():
        raise RuntimeError("redis://:super-secret@internal-redis/0")

    monkeypatch.setattr(health, "_check_database", _healthy_database)
    monkeypatch.setattr(health, "_check_vector_store", _healthy_vector_store)
    monkeypatch.setattr(health, "_check_redis", _boom)
    resp = client.get("/health/ready")

    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] == {
        "ok": False,
        "error": "dependency_unavailable",
    }
    assert "super-secret" not in resp.text


def test_ready_bounds_a_hung_redis_eval(monkeypatch):
    import api.routes.health as health

    def _healthy_database():
        return {"ok": True}

    async def _healthy_vector_store():
        return {"ok": True}

    async def _hang():
        await asyncio.Event().wait()

    monkeypatch.setattr(health, "_READY_CHECK_TIMEOUT_S", 0.01)
    monkeypatch.setattr(health, "_check_database", _healthy_database)
    monkeypatch.setattr(health, "_check_vector_store", _healthy_vector_store)
    monkeypatch.setattr(health, "_check_redis", _hang)
    resp = client.get("/health/ready")

    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] == {"ok": False, "error": "timeout"}


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
    """The capability requires fresh beat-to-automation-queue proof."""
    monkeypatch.setattr("api.routes.health._scheduler_available", lambda: False)
    caps = client.get("/capabilities").json()
    assert caps["scheduler"] is False
    assert caps["automation_cadences"] == ["manual"]

    monkeypatch.setattr("api.routes.health._scheduler_available", lambda: True)
    caps = client.get("/capabilities").json()
    assert caps["scheduler"] is True
    assert caps["automation_cadences"] == ["manual", "hourly", "daily", "weekly"]


def test_scheduler_false_when_heartbeat_check_raises(monkeypatch):
    """A dead/unreachable broker must fail closed to no scheduler, not error."""

    def _boom():
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr("workers.scheduler_health._client", _boom)
    from workers.scheduler_health import scheduler_available

    assert scheduler_available() is False
