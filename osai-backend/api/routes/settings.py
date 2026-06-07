"""Settings endpoints — data-routing tier configuration."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.models import Org
from db.repositories import try_db
from db.session import get_db, get_org_id

router = APIRouter(prefix="/settings", tags=["settings"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]

DEFAULT_DATA_ROUTING = {
    "normal": {
        "allowed_connectors": ["notion", "slack", "freshdesk", "google_drive"],
        "llm_allowed": True,
    },
    "amber": {"allowed_connectors": ["notion", "freshdesk"], "llm_allowed": False},
    "red": {"allowed_connectors": [], "llm_allowed": False},
}


class DataRoutingUpdate(BaseModel):
    routing: dict


@router.get("/data-routing")
async def get_data_routing(db: DbSession, org_id: OrgId) -> dict:
    """Return current data-routing tier configuration for the org."""

    def _from_db() -> dict:
        org = db.get(Org, org_id)
        if org and org.data_routing:
            return org.data_routing
        return DEFAULT_DATA_ROUTING

    return try_db("get_data_routing", DEFAULT_DATA_ROUTING, _from_db)


@router.patch("/data-routing")
async def update_data_routing(body: DataRoutingUpdate, db: DbSession, org_id: OrgId) -> dict:
    """Update the data-routing configuration for the org."""

    def _update() -> dict:
        org = db.get(Org, org_id)
        if org is None:
            # If org doesn't exist yet, return the new routing as-is
            return body.routing
        org.data_routing = body.routing
        db.commit()
        return org.data_routing

    return try_db("update_data_routing", body.routing, _update)
