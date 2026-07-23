"""Decision log CRUD (/decisions) — durable backend for the Decisions page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.main import app
from api.routes.decisions import _serialize
from db.models import DecisionRecord, utc_iso

client = TestClient(app)


def test_decision_crud_roundtrip():
    created = client.post(
        "/decisions",
        json={
            "title": "Standardize on Qdrant",
            "status": "proposed",
            "impact": "high",
            "owner": "ishika",
            "tags": ["infra"],
            "identified_by": "osai",
        },
    ).json()
    try:
        assert created["identifiedBy"] == "osai"
        assert created["tags"] == ["infra"]
        assert created["date"].endswith("Z")
        assert created["updated_at"].endswith("Z")

        rows = client.get("/decisions").json()
        assert any(r["id"] == created["id"] for r in rows)

        updated = client.patch(f"/decisions/{created['id']}", json={"status": "approved"}).json()
        assert updated["status"] == "approved"
        assert updated["title"] == "Standardize on Qdrant"  # untouched
    finally:
        assert client.delete(f"/decisions/{created['id']}").json()["deleted"] is True
    assert all(r["id"] != created["id"] for r in client.get("/decisions").json())


def test_validation_and_missing_rows():
    assert client.post("/decisions", json={"title": "x", "status": "maybe"}).status_code == 400
    assert client.post("/decisions", json={"title": "x", "impact": "huge"}).status_code == 400
    assert client.patch("/decisions/nope", json={"status": "approved"}).status_code == 404
    assert client.delete("/decisions/nope").status_code == 404


def test_decisions_require_auth():
    from db.session import get_org_id

    app.dependency_overrides.pop(get_org_id, None)
    resp = TestClient(app).get("/decisions")
    assert resp.status_code == 401


def test_utc_iso_treats_naive_database_values_as_utc():
    naive = datetime(2026, 7, 22, 9, 30, 15, 123456)
    same_in_india = naive.replace(tzinfo=UTC).astimezone(timezone(timedelta(hours=5, minutes=30)))

    assert utc_iso(naive) == "2026-07-22T09:30:15.123456Z"
    assert utc_iso(same_in_india) == utc_iso(naive)

    api_row = _serialize(
        DecisionRecord(
            id="decision-utc-test",
            org_id="demo-org",
            title="UTC contract",
            status="proposed",
            impact="low",
            owner=None,
            source="Manual",
            identified_by="source",
            tags=None,
            decided_at=naive,
            updated_at=same_in_india,
        )
    )
    assert api_row["date"] == "2026-07-22T09:30:15.123456Z"
    assert api_row["updated_at"] == api_row["date"]
