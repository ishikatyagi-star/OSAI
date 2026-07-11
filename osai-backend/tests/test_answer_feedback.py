"""Answer feedback capture (POST/GET /feedback)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _submit(**overrides):
    body = {
        "conversation_id": "conv-1",
        "query": "Who owns the VPC setup?",
        "answer": "Alice owns it.",
        "rating": "down",
        "comment": "Cited the wrong runbook.",
        "wrong_sources": ["Old VPC runbook"],
        "retrieval_trace": {
            "via": "osai",
            "model_route": "gemini",
            "citations": [
                {"title": "Old VPC runbook", "tool": "notion", "score": 0.81, "tier": "normal"}
            ],
        },
    }
    body.update(overrides)
    return client.post("/feedback", json=body)


def test_submit_and_list_feedback_roundtrip():
    resp = _submit()
    assert resp.status_code == 200
    fid = resp.json()["id"]
    assert resp.json()["recorded"] is True

    rows = client.get("/feedback").json()
    mine = next(r for r in rows if r["id"] == fid)
    assert mine["rating"] == "down"
    assert mine["wrong_sources"] == ["Old VPC runbook"]
    assert mine["retrieval_trace"]["citations"][0]["score"] == 0.81


def test_rating_filter_and_validation():
    up = _submit(rating="up", comment=None, wrong_sources=None).json()["id"]
    only_up = client.get("/feedback", params={"rating": "up"}).json()
    assert any(r["id"] == up for r in only_up)
    assert all(r["rating"] == "up" for r in only_up)

    assert _submit(rating="meh").status_code == 422


def test_feedback_requires_auth():
    from db.session import get_org_id

    app.dependency_overrides.pop(get_org_id, None)
    resp = TestClient(app).post(
        "/feedback",
        json={"query": "q", "answer": "a", "rating": "up"},
    )
    assert resp.status_code == 401


def test_list_requires_admin():
    from db.session import require_admin

    app.dependency_overrides.pop(require_admin, None)
    resp = TestClient(app).get("/feedback")
    assert resp.status_code == 401
