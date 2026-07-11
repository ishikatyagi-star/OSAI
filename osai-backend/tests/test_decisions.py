"""Decision log CRUD (/decisions) — durable backend for the Decisions page."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

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

        rows = client.get("/decisions").json()
        assert any(r["id"] == created["id"] for r in rows)

        updated = client.patch(
            f"/decisions/{created['id']}", json={"status": "approved"}
        ).json()
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
