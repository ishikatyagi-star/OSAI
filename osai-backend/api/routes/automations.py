"""Automations — natural-language tasks that run on a cadence or on demand.

The executor is intentionally a thin seam: `_run` calls OSAI's in-house agent
(`run_ask`) today, and can be repointed at a Hermes sidecar later without
changing the API or UI.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.automation_runner import execute_automation
from db.models import Automation, User
from db.repositories import (
    create_automation,
    delete_automation,
    list_automations,
    update_automation,
)
from db.session import get_db, get_optional_claims, get_org_id

router = APIRouter(prefix="/automations", tags=["automations"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

VALID_CADENCES = ("manual", "hourly", "daily", "weekly")
VALID_STATUSES = ("draft", "active", "paused")


class AutomationCreate(BaseModel):
    name: str
    prompt: str
    cadence: str = "manual"
    status: str = "active"


class AutomationUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    cadence: str | None = None
    enabled: bool | None = None
    status: str | None = None


def _serialize(a: Automation) -> dict[str, object]:
    return {
        "id": a.id,
        "name": a.name,
        "prompt": a.prompt,
        "cadence": a.cadence,
        "enabled": a.enabled,
        # Legacy rows may predate `status`; enabled=False reads as paused.
        "status": (a.status or "active") if a.enabled else "paused",
        "last_run_at": a.last_run_at.isoformat() if a.last_run_at else None,
        "last_result": a.last_result,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.get("")
async def list_(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    return [_serialize(a) for a in list_automations(db, org_id)]


@router.post("")
async def create_(body: AutomationCreate, db: DbSession, org_id: OrgId) -> dict[str, object]:
    if not body.name.strip() or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Name and prompt are required.")
    cadence = body.cadence if body.cadence in VALID_CADENCES else "manual"
    status = body.status if body.status in VALID_STATUSES else "active"
    a = create_automation(
        db, org_id=org_id, user_id=None, name=body.name.strip(),
        prompt=body.prompt.strip(), cadence=cadence, status=status,
    )
    return _serialize(a)


@router.patch("/{automation_id}")
async def update_(
    automation_id: str, body: AutomationUpdate, db: DbSession, org_id: OrgId
) -> dict[str, object]:
    if body.cadence is not None and body.cadence not in VALID_CADENCES:
        raise HTTPException(status_code=400, detail=f"cadence must be one of {VALID_CADENCES}.")
    if body.status is not None and body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}.")
    if body.name is not None and not body.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty.")
    if body.prompt is not None and not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
    a = update_automation(
        db, org_id, automation_id,
        name=body.name.strip() if body.name else None,
        prompt=body.prompt.strip() if body.prompt else None,
        cadence=body.cadence, enabled=body.enabled, status=body.status,
    )
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found.")
    return _serialize(a)


@router.delete("/{automation_id}")
async def delete_(automation_id: str, db: DbSession, org_id: OrgId) -> dict[str, object]:
    if not delete_automation(db, org_id, automation_id):
        raise HTTPException(status_code=404, detail="Automation not found.")
    return {"deleted": True}


@router.post("/{automation_id}/run")
async def run_(
    automation_id: str, db: DbSession, org_id: OrgId, claims: OptionalClaims
) -> dict[str, object]:
    """Run an automation now through the shared runner (the Celery beat scheduler
    uses the same runner, so manual and scheduled runs behave identically)."""
    auto = db.get(Automation, automation_id)
    if auto is None or auto.org_id != org_id:
        raise HTTPException(status_code=404, detail="Automation not found.")

    # Resolve the acting user's identity + permissions so a per-user Hermes runs
    # in their isolated context and OSAI can scope any retrieval to their access.
    user_id = claims.get("sub") if claims else None
    permissions: list[str] | None = None
    if user_id:
        user = db.get(User, user_id)
        if user:
            permissions = list(user.permissions or [])

    return await execute_automation(db, auto, user_id=user_id, permissions=permissions)
