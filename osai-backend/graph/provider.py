"""Builds the org knowledge graph from existing Postgres records.

Derives a typed graph (people, sources, tickets, decisions) with real edges
(owns, decided) from FK relationships. This is the interim provider; Phase 4
swaps in a gbrain-backed provider behind the same `build_graph` interface.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from api.schemas.graph import GraphEdge, GraphEntity
from db.models import ActionItemRecord, SourceDocumentRecord, WorkflowRun


def _person_id(email: str) -> str:
    return f"person:{email}"


def _person_label(email: str) -> str:
    return email.split("@")[0].replace(".", " ").replace("_", " ").title()


def _first_line(text: str | None) -> str:
    if not text:
        return ""
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


def build_graph(session: Session, org_id: str) -> tuple[list[GraphEntity], list[GraphEdge]]:
    docs = (
        session.query(SourceDocumentRecord)
        .filter(SourceDocumentRecord.org_id == org_id)
        .all()
    )
    items = (
        session.query(ActionItemRecord)
        .join(WorkflowRun, ActionItemRecord.workflow_run_id == WorkflowRun.id)
        .filter(WorkflowRun.org_id == org_id)
        .all()
    )
    runs = session.query(WorkflowRun).filter(WorkflowRun.org_id == org_id).all()

    entities: dict[str, GraphEntity] = {}
    edges: list[GraphEdge] = []

    # Sources (documents ingested from connectors).
    for doc in docs:
        entities[f"source:{doc.id}"] = GraphEntity(
            id=f"source:{doc.id}",
            type="source",
            label=doc.title or "Untitled",
            summary=(doc.text or "")[:160] or None,
            source_tool=doc.source_type,
            attributes={"url": doc.url} if doc.url else {},
        )

    # Decisions (meeting workflow runs).
    for run in runs:
        entities[f"decision:{run.id}"] = GraphEntity(
            id=f"decision:{run.id}",
            type="decision",
            label=_first_line(run.input_text)[:80] or run.kind,
            summary=None,
            attributes={"kind": run.kind, "status": run.status},
        )

    # Tickets (action items) + people (owners) + edges.
    for item in items:
        ticket_id = f"ticket:{item.id}"
        entities[ticket_id] = GraphEntity(
            id=ticket_id,
            type="ticket",
            label=item.title,
            summary=item.source_quote or None,
            source_tool=item.destination if item.destination != "manual" else None,
            attributes={"status": item.status},
        )
        if item.owner:
            pid = _person_id(item.owner)
            if pid not in entities:
                entities[pid] = GraphEntity(
                    id=pid,
                    type="person",
                    label=_person_label(item.owner),
                    attributes={"email": item.owner},
                )
            edges.append(
                GraphEdge(
                    id=f"owns:{item.id}",
                    source_id=pid,
                    target_id=ticket_id,
                    type="owns",
                    label="owns",
                    confidence=round(float(item.confidence or 1.0), 3),
                )
            )
        decision_id = f"decision:{item.workflow_run_id}"
        if decision_id in entities:
            edges.append(
                GraphEdge(
                    id=f"decided:{item.id}",
                    source_id=decision_id,
                    target_id=ticket_id,
                    type="decided",
                    label="decided",
                )
            )

    # Degree = number of edges touching each entity.
    degree: Counter[str] = Counter()
    for edge in edges:
        degree[edge.source_id] += 1
        degree[edge.target_id] += 1
    for entity in entities.values():
        entity.degree = degree[entity.id]

    return list(entities.values()), edges
