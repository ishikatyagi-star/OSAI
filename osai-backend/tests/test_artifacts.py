"""Saved artifacts CRUD."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_save_list_delete_roundtrip():
    a = client.post(
        "/artifacts",
        json={
            "title": "Open SLA escalations",
            "kind": "source_table",
            "data": {"rows": [{"cells": ["T-1", "open"]}]},
            "thread_id": None,
        },
    ).json()
    assert a["title"] == "Open SLA escalations"
    assert any(x["id"] == a["id"] for x in client.get("/artifacts").json())
    assert client.delete(f"/artifacts/{a['id']}").json()["deleted"] is True
    assert client.delete(f"/artifacts/{a['id']}").status_code == 404
