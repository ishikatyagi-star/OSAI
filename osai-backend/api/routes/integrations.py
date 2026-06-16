from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from connectors.registry import connector_registry
from connectors.sync_service import sync_connector
from db.repositories import get_tier_rules, set_tier_rules, try_db
from db.repositories import list_integrations as list_db_integrations
from db.session import get_db, get_org_id

router = APIRouter(prefix="/integrations", tags=["integrations"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]


@router.get("")
async def list_integrations(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    fallback = [connector.summary() for connector in connector_registry.all()]
    return try_db(
        "list_integrations",
        fallback,
        lambda: list_db_integrations(db, org_id) or fallback,
    )


@router.post("/{connector_key}/sync")
async def trigger_sync(connector_key: str, db: DbSession, org_id: OrgId) -> dict[str, object]:
    if connector_key not in {connector.key for connector in connector_registry.all()}:
        raise HTTPException(status_code=404, detail="Unknown connector")
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
