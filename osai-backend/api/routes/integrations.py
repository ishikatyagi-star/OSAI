from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from connectors.composio_ingest import ingest_composio_toolkit
from connectors.composio_tool import get_default_composio_client
from connectors.registry import connector_registry
from connectors.sync_service import sync_connector
from connectors.toolkit_map import NATIVE_TO_COMPOSIO, to_native_key
from db.models import SourceDocumentRecord
from db.repositories import get_tier_rules, set_tier_rules, try_db
from db.repositories import list_integrations as list_db_integrations
from db.session import get_db, get_org_id

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
            active = {
                to_native_key(c["toolkit"])
                for c in connections
                if c.get("toolkit") and (c.get("status") or "").upper() == "ACTIVE"
            }
            by_key = {it["key"]: it for it in items}
            for key in active:
                if key in by_key and by_key[key]["auth_state"] != "connected":
                    by_key[key]["auth_state"] = "connected"
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


@router.post("/{connector_key}/sync")
async def trigger_sync(connector_key: str, db: DbSession, org_id: OrgId) -> dict[str, object]:
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
            return await ingest_composio_toolkit(org_id, slug, db)

    return await sync_connector(connector_key, org_id, db)


class TierRule(BaseModel):
    pattern: str
    tier: str


class TierRulesBody(BaseModel):
    rules: list[TierRule]


@router.get("/{connector_key}/tier-rules")
async def list_tier_rules(connector_key: str, db: DbSession, org_id: OrgId) -> dict[str, object]:
    """Return per-info sensitivity rules for a connector (path/keyword → tier)."""
    if connector_key not in {c.key for c in connector_registry.all()}:
        raise HTTPException(status_code=404, detail="Unknown connector")
    return {"connector_key": connector_key, "rules": get_tier_rules(db, org_id, connector_key)}


@router.put("/{connector_key}/tier-rules")
async def update_tier_rules(
    connector_key: str, body: TierRulesBody, db: DbSession, org_id: OrgId
) -> dict[str, object]:
    """Replace the per-info sensitivity rules for a connector."""
    if connector_key not in {c.key for c in connector_registry.all()}:
        raise HTTPException(status_code=404, detail="Unknown connector")
    saved = set_tier_rules(
        db, org_id, connector_key, [r.model_dump() for r in body.rules]
    )
    return {"connector_key": connector_key, "rules": saved}


@router.get("/{connector_key}/healthcheck")
async def connector_healthcheck(connector_key: str, org_id: OrgId) -> dict[str, object]:
    if connector_key not in {connector.key for connector in connector_registry.all()}:
        raise HTTPException(status_code=404, detail="Unknown connector")
    connector = connector_registry.get(connector_key)
    result = await connector.healthcheck(org_id)
    return {
        "connector_key": result.connector_key,
        "healthy": result.healthy,
        "message": result.message,
    }
