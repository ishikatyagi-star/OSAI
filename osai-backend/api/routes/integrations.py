import asyncio
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
from db.session import SessionLocal, get_db, get_org_id, require_admin, require_writable_org

router = APIRouter(prefix="/integrations", tags=["integrations"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
AdminOnly = Annotated[dict, Depends(require_admin)]


@router.get("")
async def list_integrations(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    # Only integrations the org has actually configured. A fresh workspace gets
    # an empty list — the frontend renders its empty state pointing at the full
    # Composio catalog instead of a fixed set of native connector cards.
    items = try_db("list_integrations", [], lambda: list_db_integrations(db, org_id))
    items = [it for it in items if it.get("auth_state") != "not_configured"]

    # Overlay live Composio connections onto the matching native card so an
    # authorized app reads "connected" even if ingestion hasn't run yet. The
    # Composio slug maps to one native key, keeping it a single card.
    client = get_default_composio_client()
    if client.available():
        try:
            # Bounded well under the frontend's fetch budget: if Composio is
            # slow the page must still render from the DB (overlay is optional),
            # not time out client-side and show a load error.
            connections = await asyncio.wait_for(client.list_connections(org_id), timeout=4)
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

        # Attach Composio-hosted logos so the frontend never hardcodes brand
        # icons. Cached per slug in-process, bounded so a slow Composio can't
        # stall the page; a missing logo just renders the generic fallback.
        try:
            slugs = [NATIVE_TO_COMPOSIO.get(it["key"], it["key"]) for it in items]
            logos = await asyncio.wait_for(
                asyncio.gather(*(client.toolkit_logo(slug) for slug in slugs)),
                timeout=4,
            )
            for it, logo in zip(items, logos):
                it["logo"] = logo
        except Exception:  # noqa: BLE001 — logo enrichment is best-effort
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


# One ingest per (org, toolkit) at a time. Double-clicking "Sync Now" (or a UI
# retry) used to stack two full ingests in the same process, doubling memory
# pressure on the tiny prod instance — the second click should be a no-op.
_INFLIGHT_INGESTS: set[tuple[str, str]] = set()


async def _ingest_composio_in_background(org_id: str, slug: str) -> None:
    """Run a Composio re-ingest off the request path, with its own DB session.

    A full re-sync (25 files + media transcription + embeddings) easily exceeds
    the client's request timeout; run inline it left the UI stuck on "Syncing…"
    and the request was cancelled before ingest_composio_toolkit could record a
    sync run — so /sync-runs showed nothing. As a background task it always runs
    to completion and records its result.
    """
    key = (org_id, slug)
    if key in _INFLIGHT_INGESTS:
        return
    _INFLIGHT_INGESTS.add(key)
    try:
        with SessionLocal() as db:
            try:
                await ingest_composio_toolkit(org_id, slug, db)
            except Exception:  # noqa: BLE001 — recorded as a failed run inside; never crash
                pass
    finally:
        _INFLIGHT_INGESTS.discard(key)


@router.post("/{connector_key}/sync")
async def trigger_sync(
    connector_key: str,
    db: DbSession,
    org_id: WriteOrgId,
    background_tasks: BackgroundTasks,
    _admin: AdminOnly,
) -> dict[str, object]:
    # Catalog apps (e.g. Gmail) have no native connector, so an unknown key is
    # only an error when there's also no active Composio connection for it.
    is_native = connector_key in {connector.key for connector in connector_registry.all()}

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

    if not is_native:
        raise HTTPException(status_code=404, detail="Unknown connector")
    return await sync_connector(connector_key, org_id, db)


@router.get("/{connector_key}/healthcheck")
async def connector_healthcheck(connector_key: str, org_id: OrgId) -> dict[str, object]:
    # Catalog apps have no native connector; only 404 when Composio has no
    # active connection for the key either (checked below).
    is_native = connector_key in {connector.key for connector in connector_registry.all()}

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

    if not is_native:
        raise HTTPException(status_code=404, detail="Unknown connector")
    connector = connector_registry.get(connector_key)
    result = await connector.healthcheck(org_id)
    return {
        "connector_key": result.connector_key,
        "healthy": result.healthy,
        "message": result.message,
    }
