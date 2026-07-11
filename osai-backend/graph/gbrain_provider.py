"""gbrain-backed org knowledge graph (Phase 4).

When gbrain is configured (OSAI_GBRAIN_HOME), documents mirrored at ingest time
(db/repositories.upsert_source_documents → memory/gbrain_client.mirror_documents)
become pages whose wikilink/typed edges gbrain wires itself. This provider maps
those pages + edges into the same GraphEntity/GraphEdge shapes as the interim
Postgres provider (graph/provider.py), behind the same build_graph seam.
"""

from __future__ import annotations

import logging

from api.schemas.graph import GraphEdge, GraphEntity
from memory.gbrain_client import get_org_gbrain_client

logger = logging.getLogger("osai.graph")

# gbrain page types → OSAI graph entity types (fallback: source, since mirrored
# pages are connector documents).
_PAGE_TYPE_MAP = {
    "person": "person",
    "project": "project",
    "decision": "decision",
    "ticket": "ticket",
}

# gbrain edge types → OSAI edge types (fallback: references — wikilink default).
_EDGE_TYPE_MAP = {
    "owns": "owns",
    "blocks": "blocks",
    "decided": "decided",
    "references": "references",
}

_MAX_PAGES = 50  # each page's edges cost one CLI call; cap the fan-out


def gbrain_graph_available(org_id: str) -> bool:
    return get_org_gbrain_client(org_id).available()


def build_graph_gbrain(org_id: str) -> tuple[list[GraphEntity], list[GraphEdge]]:
    """Entities + edges from the org's gbrain. Returns ([], []) on any failure
    so the caller can fall back to the Postgres-derived graph."""
    client = get_org_gbrain_client(org_id)
    if not client.available():
        return [], []
    try:
        pages = client.list_pages(limit=_MAX_PAGES)
    except Exception as exc:  # noqa: BLE001 — sidecar is best-effort
        logger.warning("gbrain list_pages failed: %s", exc)
        return [], []
    if not pages:
        return [], []

    entities: dict[str, GraphEntity] = {}
    for page in pages:
        slug = page.get("slug") or ""
        if not slug:
            continue
        entities[slug] = GraphEntity(
            id=f"page:{slug}",
            type=_PAGE_TYPE_MAP.get(page.get("type") or "", "source"),
            label=page.get("title") or slug,
            summary=None,
            source_tool="gbrain",
        )

    edges: dict[str, GraphEdge] = {}
    for slug in entities:
        try:
            paths = client.graph_query(slug, depth=1)
        except Exception:  # noqa: BLE001
            continue
        for path in paths:
            src = path.get("from_slug") or path.get("from") or slug
            dst = path.get("to_slug") or path.get("to")
            if not dst or src not in entities or dst not in entities:
                continue
            edge_type = _EDGE_TYPE_MAP.get(path.get("type") or "", "references")
            edge_id = f"edge:{src}->{dst}:{edge_type}"
            if edge_id in edges:
                continue
            edges[edge_id] = GraphEdge(
                id=edge_id,
                source_id=f"page:{src}",
                target_id=f"page:{dst}",
                type=edge_type,
                label=path.get("type") or "references",
                source_tool="gbrain",
            )

    # Degree counts, mirroring the Postgres provider's behaviour.
    for edge in edges.values():
        for node_id in (edge.source_id, edge.target_id):
            slug = node_id.removeprefix("page:")
            if slug in entities:
                entities[slug].degree += 1

    return list(entities.values()), list(edges.values())
