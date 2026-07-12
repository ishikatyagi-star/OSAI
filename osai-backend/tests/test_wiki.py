"""Org wiki: CRUD, revisions, suggestions from decisions/corrections."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _cleanup(entry_id: str):
    client.delete(f"/wiki/{entry_id}")


def test_create_edit_revision_roundtrip():
    e = client.post("/wiki", json={"title": "Deploy policy", "content": "Fridays only."}).json()
    assert e["status"] == "published"

    updated = client.patch(f"/wiki/{e['id']}", json={"content": "Fridays after standup."}).json()
    assert updated["content"] == "Fridays after standup."

    revs = client.get(f"/wiki/{e['id']}/revisions").json()
    assert len(revs) == 1 and revs[0]["content"] == "Fridays only."
    _cleanup(e["id"])


def test_decision_creates_wiki_suggestion():
    d = client.post(
        "/decisions",
        json={"title": "Adopt Qdrant for vectors", "status": "approved", "impact": "high"},
    ).json()
    entries = client.get("/wiki").json()
    sug = [
        x for x in entries if x["status"] == "suggested" and "Adopt Qdrant" in x["title"]
    ]
    assert sug, entries
    # Approving publishes it.
    approved = client.patch(f"/wiki/{sug[0]['id']}", json={"status": "published"}).json()
    assert approved["status"] == "published"
    _cleanup(sug[0]["id"])
    client.delete(f"/decisions/{d['id']}")


def test_correction_creates_wiki_suggestion():
    from unittest.mock import patch

    with patch("api.routes.feedback.record_memory"):
        client.post(
            "/feedback",
            json={
                "query": "what's the deploy window?",
                "answer": "Anytime.",
                "rating": "down",
                "correction": "Fridays after standup only.",
            },
        )
    entries = client.get("/wiki").json()
    sug = [x for x in entries if x["status"] == "suggested" and "deploy window" in x["title"]]
    assert sug, entries
    _cleanup(sug[0]["id"])


def test_bad_status_transition_rejected():
    e = client.post("/wiki", json={"title": "T", "content": "C"}).json()
    assert client.patch(f"/wiki/{e['id']}", json={"status": "archived"}).status_code == 422
    _cleanup(e["id"])


def test_unknown_entry_404():
    assert client.get("/wiki/nope/revisions").status_code == 404
