"""Builds the org knowledge graph from existing Postgres records.

Derives a typed graph (people, sources, tickets, decisions) with real edges
(owns, decided) from FK relationships. This is the interim provider; Phase 4
swaps in a gbrain-backed provider behind the same `build_graph` interface.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from api.schemas.graph import GraphEdge, GraphEntity
from db.models import (
    ActionItemRecord,
    ConnectorAccount,
    ConnectorRecord,
    SourceDocumentRecord,
    User,
    WorkflowRun,
)
from memory.retriever import _visible

_TIER_RANK = {"normal": 0, "amber": 1, "red": 2}


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


def build_access_graph(session: Session, org_id: str) -> dict:
    """Who-can-access-what map: users (by role) ↔ connectors they can reach.

    Each access edge carries the highest data tier the user is cleared for in that
    connector, derived from the same permission rule the retriever enforces
    (`_visible`). This is the "org chart of access", not an entity explorer.
    """
    users = session.query(User).filter(User.org_id == org_id).all()
    accounts = (
        session.query(ConnectorAccount)
        .filter(ConnectorAccount.org_id == org_id)
        .all()
    )
    records = {r.key: r for r in session.query(ConnectorRecord).all()}
    docs = (
        session.query(SourceDocumentRecord)
        .filter(SourceDocumentRecord.org_id == org_id)
        .all()
    )

    # Group documents (tier + permissions) by connector key (== source_type).
    docs_by_connector: dict[str, list[SourceDocumentRecord]] = {}
    for doc in docs:
        docs_by_connector.setdefault(doc.source_type, []).append(doc)

    connector_keys = [a.connector_key for a in accounts] or list(docs_by_connector)
    connectors = [
        {
            "key": key,
            "label": records[key].display_name if key in records else key.title(),
            "connected": next(
                (a.auth_state == "connected" for a in accounts if a.connector_key == key),
                False,
            ),
        }
        for key in dict.fromkeys(connector_keys)  # de-dupe, preserve order
    ]

    user_nodes = [
        {"id": u.id, "label": u.display_name or u.email, "role": u.role}
        for u in users
    ]

    access: list[dict] = []
    for u in users:
        for c in connectors:
            visible_docs = [
                d
                for d in docs_by_connector.get(c["key"], [])
                if _visible(d.permissions, u.permissions)
            ]
            # A user with no visible docs in a connector still has access to the
            # tool itself if it's connected and they're an admin/source:all holder.
            is_privileged = (
                not u.permissions
                or "role:admin" in u.permissions
                or "org:admin" in u.permissions
                or "source:all" in u.permissions
            )
            if not visible_docs and not (c["connected"] and is_privileged):
                continue
            top_tier = "normal"
            for d in visible_docs:
                if _TIER_RANK.get(d.data_tier, 0) > _TIER_RANK.get(top_tier, 0):
                    top_tier = d.data_tier
            access.append(
                {
                    "user_id": u.id,
                    "connector_key": c["key"],
                    "tier": top_tier,
                    "doc_count": len(visible_docs),
                }
            )

    return {"users": user_nodes, "connectors": connectors, "access": access}
