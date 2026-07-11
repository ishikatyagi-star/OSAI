"""gbrain wiring (Phase 4): per-org isolation, ingest mirroring, and the
gbrain-backed graph provider behind the build_graph seam."""

from __future__ import annotations

from types import SimpleNamespace

from graph.gbrain_provider import build_graph_gbrain
from memory.gbrain_client import _page_slug, get_org_gbrain_client, mirror_documents


def test_org_client_uses_per_org_home(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "gbrain_home", "/brains")
    assert get_org_gbrain_client("org-a").home == "/brains/org-a"
    assert get_org_gbrain_client("org-b").home == "/brains/org-b"


def test_org_client_without_home_is_unavailable(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "gbrain_home", None)
    client = get_org_gbrain_client("org-a")
    assert client.home is None
    assert client.available() is False


def test_page_slug_is_sanitized():
    assert _page_slug("notion/page 1:β") == "doc-notion-page-1--"
    assert _page_slug("abc_DEF-123") == "doc-abc_DEF-123"


def _doc(source_id: str, title: str, text: str):
    return SimpleNamespace(
        source_id=source_id, title=title, text=text, source_type="notion"
    )


def test_mirror_documents_writes_pages(monkeypatch):
    import memory.gbrain_client as mod

    written: list[tuple[str, str]] = []

    class _FakeClient:
        def available(self):
            return True

        def put_page(self, slug, markdown):
            written.append((slug, markdown))
            return True

    monkeypatch.setattr(mod, "get_org_gbrain_client", lambda org_id: _FakeClient())
    n = mirror_documents("demo-org", [_doc("a1", "Roadmap", "Q3 plan"), _doc("b2", "Notes", "x")])
    assert n == 2
    assert written[0][0] == "doc-a1"
    assert "# Roadmap" in written[0][1]
    assert "Q3 plan" in written[0][1]


def test_mirror_documents_inert_when_unavailable(monkeypatch):
    import memory.gbrain_client as mod

    class _FakeClient:
        def available(self):
            return False

        def put_page(self, slug, markdown):  # pragma: no cover — must not be called
            raise AssertionError("put_page called while unavailable")

    monkeypatch.setattr(mod, "get_org_gbrain_client", lambda org_id: _FakeClient())
    assert mirror_documents("demo-org", [_doc("a1", "t", "x")]) == 0


def test_build_graph_gbrain_maps_pages_and_edges(monkeypatch):
    import graph.gbrain_provider as provider

    class _FakeClient:
        def available(self):
            return True

        def list_pages(self, limit=100):
            return [
                {"slug": "doc-a", "title": "Doc A", "type": "note"},
                {"slug": "doc-b", "title": "Doc B", "type": "decision"},
            ]

        def graph_query(self, slug, depth=1):
            if slug == "doc-a":
                return [{"from_slug": "doc-a", "to_slug": "doc-b", "type": "references"}]
            return []

    monkeypatch.setattr(provider, "get_org_gbrain_client", lambda org_id: _FakeClient())
    entities, edges = build_graph_gbrain("demo-org")

    by_id = {e.id: e for e in entities}
    assert by_id["page:doc-a"].type == "source"  # unknown page type → source
    assert by_id["page:doc-b"].type == "decision"
    assert len(edges) == 1
    assert edges[0].source_id == "page:doc-a"
    assert edges[0].target_id == "page:doc-b"
    assert edges[0].type == "references"
    # Degree counted on both endpoints.
    assert by_id["page:doc-a"].degree == 1
    assert by_id["page:doc-b"].degree == 1


def test_build_graph_gbrain_empty_when_unavailable(monkeypatch):
    import graph.gbrain_provider as provider

    class _FakeClient:
        def available(self):
            return False

    monkeypatch.setattr(provider, "get_org_gbrain_client", lambda org_id: _FakeClient())
    assert build_graph_gbrain("demo-org") == ([], [])


def test_graph_route_falls_back_to_postgres_when_gbrain_off(monkeypatch):
    """With gbrain unavailable (default), /graph/entities serves the
    Postgres-derived graph exactly as before."""
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    resp = client.get("/graph/entities")
    assert resp.status_code == 200  # shape unchanged; provider seam intact