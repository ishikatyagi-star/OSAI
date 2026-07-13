from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from connectors.composio_ingest import ingest_composio_toolkit
from connectors.composio_tool import get_default_composio_client
from connectors.registry import connector_registry
from connectors.sync_service import sync_connector
from connectors.toolkit_map import NATIVE_TO_COMPOSIO, to_native_key
from db.models import SourceDocumentRecord
from db.repositories import list_integrations as list_db_integrations
from db.repositories import try_db
from db.session import SessionLocal, get_db, get_org_id

router = APIRouter(prefix="/integrations", tags=["integrations"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]


@router.get("")
async def list_integrations(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    fallback = [connector.summary() for connector in connector_registry.all()]
    items = try_db(
        "list_integrations",
        fallback,
        lambda: list_db_integrations(db, org_id) or fallback,
    )

    # Overlay live Composio connections onto the matching native card so an
    # authorized app reads "connected" even if ingestion hasn't run yet. The
    # Composio slug maps to one native key, keeping it a single card.
    client = get_default_composio_client()
    if client.available():
        try:
            connections = await client.list_connections(org_id)
            active: dict[str, dict] = {}
            for c in connections:
                if c.get("toolkit") and (c.get("status") or "").upper() == "ACTIVE":
                    active[to_native_key(c["toolkit"])] = c
            by_key = {it["key"]: it for it in items}
            for key, conn in active.items():
                if key in by_key:
                    by_key[key]["auth_state"] = "connected"
                    # Prefer the live account email if we have it (may be fresher
                    # than what the last sync persisted).
                    if conn.get("email") and not by_key[key].get("account_email"):
                        by_key[key]["account_email"] = conn.get("email")
                else:
                    # A catalog connector with no native counterpart (e.g. Gmail,
                    # Linear via Composio) — synthesize a card so anything the
                    # user connects from the full catalog is visible here.
                    items.append(
                        {
                            "key": key,
                            "display_name": (conn.get("toolkit") or key)
                            .replace("_", " ")
                            .title(),
                            "capabilities": ["execute"],
                            "auth_state": "connected",
                            "scopes": [],
                            "last_sync": None,
                            "sync_error": None,
                            "account_email": conn.get("email"),
                            "source": "composio",
                        }
                    )
        except Exception:  # noqa: BLE001 — connection overlay is best-effort
            pass

    return items


@router.get("/{connector_key}/documents")
async def list_connector_documents(
    connector_key: str, db: DbSession, org_id: OrgId, limit: int = 25
) -> list[dict[str, object]]:
    """Recently indexed documents for a connector, so the UI can show what synced."""
    rows = db.scalars(
        select(SourceDocumentRecord)
        .where(
            SourceDocumentRecord.org_id == org_id,
            SourceDocumentRecord.source_type == connector_key,
        )
        .order_by(desc(SourceDocumentRecord.ingested_at))
        .limit(limit)
    ).all()
    return [
        {
            "id": d.id,
            "title": d.title or "Untitled",
            "url": d.url,
            "data_tier": d.data_tier,
            "updated_at": (
                d.source_updated_at.isoformat()
                if d.source_updated_at
                else d.ingested_at.isoformat()
            ),
        }
        for d in rows
    ]


async def _ingest_composio_in_background(org_id: str, slug: str) -> None:
    """Run a Composio re-ingest off the request path, with its own DB session.

    A full re-sync (25 files + media transcription + embeddings) easily exceeds
    the client's request timeout; run inline it left the UI stuck on "Syncing…"
    and the request was cancelled before ingest_composio_toolkit could record a
    sync run — so /sync-runs showed nothing. As a background task it always runs
    to completion and records its result.
    """
    with SessionLocal() as db:
        try:
            await ingest_composio_toolkit(org_id, slug, db)
        except Exception:  # noqa: BLE001 — recorded as a failed run inside; never crash
            pass


@router.post("/{connector_key}/sync")
async def trigger_sync(
    connector_key: str,
    db: DbSession,
    org_id: OrgId,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    if connector_key not in {connector.key for connector in connector_registry.all()}:
        raise HTTPException(status_code=404, detail="Unknown connector")

    # If this app is connected through Composio OAuth, ingest via Composio (no
    # native service-account credentials needed, e.g. Google Drive). Only fall
    # back to the native connector when there's no active Composio connection.
    client = get_default_composio_client()
    if client.available():
        slug = NATIVE_TO_COMPOSIO.get(connector_key, connector_key)
        try:
            connections = await client.list_connections(org_id)
            has_active = any(
                c.get("toolkit") == slug and (c.get("status") or "").upper() == "ACTIVE"
                for c in connections
            )
        except Exception:  # noqa: BLE001 — fall back to native sync on lookup failure
            has_active = False
        if has_active:
            # Kick the ingest off in the background and return immediately so the
            # UI can show "sync started" and poll /sync-runs for the result.
            background_tasks.add_task(_ingest_composio_in_background, org_id, slug)
            return {
                "connector_key": connector_key,
                "status": "started",
                "documents_indexed": 0,
            }

    return await sync_connector(connector_key, org_id, db)


@router.get("/{connector_key}/healthcheck")
async def connector_healthcheck(connector_key: str, org_id: OrgId) -> dict[str, object]:
    if connector_key not in {connector.key for connector in connector_registry.all()}:
        raise HTTPException(status_code=404, detail="Unknown connector")

    # If the app is connected via Composio OAuth, report on that connection rather
    # than the native connector (which would ask for service-account creds).
    client = get_default_composio_client()
    if client.available():
        slug = NATIVE_TO_COMPOSIO.get(connector_key, connector_key)
        try:
            connections = await client.list_connections(org_id)
            if any(
                c.get("toolkit") == slug and (c.get("status") or "").upper() == "ACTIVE"
                for c in connections
            ):
                return {
                    "connector_key": connector_key,
                    "healthy": True,
                    "message": "Connected via Composio (OAuth).",
                }
        except Exception:  # noqa: BLE001 — fall back to native healthcheck
            pass

    connector = connector_registry.get(connector_key)
    result = await connector.healthcheck(org_id)
    return {
        "connector_key": result.connector_key,
        "healthy": result.healthy,
        "message": result.message,
    }
