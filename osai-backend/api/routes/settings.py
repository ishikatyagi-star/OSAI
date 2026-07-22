"""Settings endpoints — data-routing tier configuration."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.models import Org
from db.session import get_db, get_org_id, require_admin, require_writable_org

# Defaults live with the egress policy (llm/policy.py) — the module that
# actually enforces them — so route and enforcement can never drift apart.
from llm.policy import (
    DEFAULT_DATA_ROUTING,
    DENY_ALL_DATA_ROUTING,
    DataRoutingPolicy,
    normalize_data_routing,
)

router = APIRouter(prefix="/settings", tags=["settings"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
WriteOrgId = Annotated[str, Depends(require_writable_org)]


class DataRoutingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routing: DataRoutingPolicy
    # None is reserved for replacing a malformed stored policy with deny-all.
    # Older clients that omit it fail closed with 409 for every valid policy.
    expected_routing: DataRoutingPolicy | None = None


def _stored_data_routing(org: Org) -> dict:
    if org.data_routing is None or org.data_routing == {}:
        return normalize_data_routing(DEFAULT_DATA_ROUTING)
    return normalize_data_routing(org.data_routing, merge_defaults=True)


@router.get("/data-routing")
async def get_data_routing(db: DbSession, org_id: OrgId) -> dict:
    """Return current data-routing tier configuration for the org."""
    try:
        org = db.get(Org, org_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Data-routing settings are temporarily unavailable.",
        ) from exc
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found.")
    try:
        return _stored_data_routing(org)
    except (TypeError, ValueError) as exc:
        # Enforcement treats the same malformed row as deny-all. Do not present
        # stale defaults to an admin as though the stored policy were healthy.
        raise HTTPException(
            status_code=503,
            detail="Stored data-routing settings are invalid.",
        ) from exc


@router.patch("/data-routing")
async def update_data_routing(
    body: DataRoutingUpdate,
    db: DbSession,
    org_id: WriteOrgId,
    _admin: Annotated[dict, Depends(require_admin)],
) -> dict:
    """Update the data-routing configuration for the org (admins only — this
    governs which data tiers may reach cloud LLMs, so members can't relax it)."""

    routing = body.routing.model_dump(mode="python")
    expected = (
        body.expected_routing.model_dump(mode="python")
        if body.expected_routing is not None
        else None
    )
    try:
        # Serialize competing admin writes, then compare the policy the client
        # actually edited. This is a native DB row lock on PostgreSQL.
        org = db.get(Org, org_id, with_for_update=True)
        if org is None:
            raise HTTPException(status_code=404, detail="Org not found.")
        try:
            current = _stored_data_routing(org)
        except (TypeError, ValueError):
            current = None
        invalid_recovery = current is None and expected is None and routing == DENY_ALL_DATA_ROUTING
        if (current is None and not invalid_recovery) or (
            current is not None and current != expected
        ):
            raise HTTPException(
                status_code=409,
                detail="Data-routing policy changed; reload before saving.",
            )
        org.data_routing = routing
        db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Data-routing settings could not be saved.",
        ) from exc
    return routing
