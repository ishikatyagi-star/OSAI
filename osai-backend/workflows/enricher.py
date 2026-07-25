"""Context enricher — fetches Qdrant knowledge chunks and Postgres action items."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from db.models import ActionItemRecord, WorkflowRun
from memory.embeddings import default_embedding_provider
from memory.qdrant_store import get_default_qdrant_store
from memory.retriever import _authoritative_document_hits, _tier_visible, _visible

logger = logging.getLogger("osai.workflows.enricher")


async def get_workflow_context_async(
    org_id: str,
    query_text: str,
    session: Session,
    limit_chunks: int = 3,
    limit_items: int = 10,
    requester_permissions: list[str] | None = None,
    requester_tier: str = "red",
    actor_user_id: str | None = None,
    viewer_is_admin: bool = False,
) -> dict[str, list[dict]]:
    """Retrieve related chunks semantically from Qdrant and recent action items from DB.

    Enrichment context lands in the extraction prompt, so it must pass the same
    governance filter as retrieval (`_visible` + clearance tier) for the user who
    initiated the workflow. System context (Zoom webhook / Celery, no initiating
    user) retains document access but cannot read user-owned action items."""
    documents = []

    # 1. Retrieve related chunks from Qdrant
    if query_text:
        try:
            qdrant = get_default_qdrant_store()
            # Embed search query text
            vectors = await default_embedding_provider.embed_texts(
                [query_text], is_query=True
            )
            query_vector = vectors[0]

            # Query Qdrant
            hits = await qdrant.search(query_vector, org_id, limit=limit_chunks)
            hits = _authoritative_document_hits(hits, org_id, session=session)
            hits = [
                h
                for h in hits
                if _visible(
                    (h.payload or {}).get("permissions"), requester_permissions or []
                )
                and _tier_visible((h.payload or {}).get("data_tier"), requester_tier)
            ]

            for hit in hits:
                payload = hit.payload or {}
                documents.append(
                    {
                        "title": payload.get("title") or "Untitled",
                        "text": payload.get("text") or payload.get("content_preview", ""),
                        "source_type": payload.get("source_type", "unknown"),
                        "url": payload.get("url"),
                        "confidence": float(hit.score),
                        "data_tier": payload.get("data_tier") or "normal",
                    }
                )
            logger.info(f"Retrieved {len(documents)} related chunks from Qdrant.")
        except Exception as exc:
            logger.error(f"Error retrieving Qdrant context for workflow: {exc}")

    # 2. Retrieve recent action items from Postgres
    action_items = []
    try:
        stmt = select(ActionItemRecord).join(
            WorkflowRun, ActionItemRecord.workflow_run_id == WorkflowRun.id
        ).where(WorkflowRun.org_id == org_id)
        if not viewer_is_admin:
            stmt = (
                stmt.where(WorkflowRun.created_by == actor_user_id)
                if actor_user_id
                else None
            )
        rows = (
            session.scalars(
                stmt.order_by(desc(ActionItemRecord.created_at)).limit(limit_items)
            ).all()
            if stmt is not None
            else []
        )
        for item in rows:
            action_items.append(
                {
                    "title": item.title,
                    "owner": item.owner,
                    "status": item.status,
                    "destination": item.destination,
                }
            )
        logger.info(f"Retrieved {len(action_items)} recent action items from Postgres.")
    except Exception as exc:
        logger.error(f"Error retrieving Postgres action items: {exc}")

    return {
        "documents": documents,
        "action_items": action_items,
    }


def get_workflow_context(
    org_id: str,
    query_text: str,
    session: Session,
    limit_chunks: int = 3,
    limit_items: int = 10,
    requester_permissions: list[str] | None = None,
    requester_tier: str = "red",
    actor_user_id: str | None = None,
    viewer_is_admin: bool = False,
) -> dict[str, list[dict]]:
    """Synchronous wrapper to retrieve context for Celery and other sync workflows."""
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            get_workflow_context_async(
                org_id=org_id,
                query_text=query_text,
                session=session,
                limit_chunks=limit_chunks,
                limit_items=limit_items,
                requester_permissions=requester_permissions,
                requester_tier=requester_tier,
                actor_user_id=actor_user_id,
                viewer_is_admin=viewer_is_admin,
            )
        )
    except Exception as exc:
        logger.error(f"Error in sync get_workflow_context wrapper: {exc}")
        return {"documents": [], "action_items": []}
