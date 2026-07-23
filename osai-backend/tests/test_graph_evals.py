"""Tests for the /graph and /evals endpoints (P4-T4, P6)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from api.schemas.graph import GraphEdge, GraphEntity
from evals.fixtures import FIXTURES

client = TestClient(app)

_ENTITY_TYPES = set(GraphEntity.model_fields["type"].annotation.__args__)
_EDGE_TYPES = set(GraphEdge.model_fields["type"].annotation.__args__)


def test_graph_entities_shape_and_filter():
    resp = client.get("/graph/entities")
    assert resp.status_code == 200
    entities = resp.json()
    assert isinstance(entities, list)
    for e in entities:
        assert {"id", "type", "label", "degree"} <= e.keys()
        assert e["type"] in _ENTITY_TYPES
    # type filter never returns a different type
    filtered = client.get("/graph/entities", params={"type": "person"}).json()
    assert all(e["type"] == "person" for e in filtered)


def test_graph_edges_shape():
    resp = client.get("/graph/edges")
    assert resp.status_code == 200
    for edge in resp.json():
        assert {"id", "source_id", "target_id", "type"} <= edge.keys()
        assert edge["type"] in _EDGE_TYPES


def test_evals_returns_full_run():
    assert client.get("/evals").status_code == 405
    resp = client.post("/evals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == len(FIXTURES)
    assert body["passed"] + body["failed"] == body["total"]
    assert 0.0 <= body["pass_rate"] <= 1.0
    assert len(body["cases"]) == len(FIXTURES)
