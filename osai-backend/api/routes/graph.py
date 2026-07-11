"""Org knowledge-graph endpoints — power the web graph inspector (P4-T4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.schemas.graph import GraphEdge, GraphEntity
from db.repositories import try_db
from db.session import get_db, get_org_id
from graph.gbrain_provider import build_graph_gbrain, gbrain_graph_available
from graph.provider import build_access_graph, build_graph

router = APIRouter(prefix="/graph", tags=["graph"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]


def _org_graph(db: Session, org_id: str) -> tuple[list[GraphEntity], list[GraphEdge]]:
    """Provider seam: gbrain-backed graph when configured and populated,
    otherwise the interim Postgres-derived graph."""
    if gbrain_graph_available(org_id):
        entities, edges = build_graph_gbrain(org_id)
        if entities:
            return entities, edges
    return try_db("build_graph", ([], []), lambda: build_graph(db, org_id))


@router.get("/entities", response_model=list[GraphEntity])
async def list_entities(
    db: DbSession,
    org_id: OrgId,
    type: str | None = None,
    q: str | None = None,
) -> list[GraphEntity]:
    entities, _ = _org_graph(db, org_id)
    if type:
        entities = [e for e in entities if e.type == type]
    if q:
        needle = q.lower()
        entities = [
            e
            for e in entities
            if needle in e.label.lower() or needle in (e.summary or "").lower()
        ]
    return entities


@router.get("/access")
async def access_map(db: DbSession, org_id: OrgId) -> dict:
    """Who-can-access-what: users (by role) ↔ connectors, annotated with the
    highest data tier each user is cleared for. Powers the simplified org graph."""
    return try_db(
        "build_access_graph",
        {"users": [], "connectors": [], "access": []},
        lambda: build_access_graph(db, org_id),
    )


@router.get("/edges", response_model=list[GraphEdge])
async def list_edges(
    db: DbSession,
    org_id: OrgId,
    entity_id: str | None = None,
) -> list[GraphEdge]:
    _, edges = _org_graph(db, org_id)
    if entity_id:
        edges = [e for e in edges if entity_id in (e.source_id, e.target_id)]
    return edges
