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

from agent.orchestrator import run_ask
from api.schemas.agent import AskRequest
from db.models import Automation
from db.repositories import (
    create_automation,
    delete_automation,
    list_automations,
    record_automation_run,
)
from db.session import get_db, get_org_id

router = APIRouter(prefix="/automations", tags=["automations"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]

VALID_CADENCES = ("manual", "hourly", "daily", "weekly")


class AutomationCreate(BaseModel):
    name: str
    prompt: str
    cadence: str = "manual"


def _serialize(a: Automation) -> dict[str, object]:
    return {
        "id": a.id,
        "name": a.name,
        "prompt": a.prompt,
        "cadence": a.cadence,
        "enabled": a.enabled,
        "last_run_at": a.last_run_at.isoformat() if a.last_run_at else None,
        "last_result": a.last_result,
    }


@router.get("")
async def list_(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    return [_serialize(a) for a in list_automations(db, org_id)]


@router.post("")
async def create_(body: AutomationCreate, db: DbSession, org_id: OrgId) -> dict[str, object]:
    if not body.name.strip() or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Name and prompt are required.")
    cadence = body.cadence if body.cadence in VALID_CADENCES else "manual"
    a = create_automation(
        db, org_id=org_id, user_id=None, name=body.name.strip(),
        prompt=body.prompt.strip(), cadence=cadence,
    )
    return _serialize(a)


@router.delete("/{automation_id}")
async def delete_(automation_id: str, db: DbSession, org_id: OrgId) -> dict[str, object]:
    if not delete_automation(db, org_id, automation_id):
        raise HTTPException(status_code=404, detail="Automation not found.")
    return {"deleted": True}


@router.post("/{automation_id}/run")
async def run_(automation_id: str, db: DbSession, org_id: OrgId) -> dict[str, object]:
    """Run an automation now: execute its prompt through the agent and store the
    result. (Recurring execution on the cadence requires the Celery beat worker.)"""
    auto = db.get(Automation, automation_id)
    if auto is None or auto.org_id != org_id:
        raise HTTPException(status_code=404, detail="Automation not found.")
    # --- executor seam: in-house agent today, swappable for a Hermes sidecar ---
    resp = await run_ask(AskRequest(org_id=org_id, question=auto.prompt))
    record_automation_run(db, automation_id, resp.answer)
    return {"id": automation_id, "result": resp.answer, "citations": resp.citations}
