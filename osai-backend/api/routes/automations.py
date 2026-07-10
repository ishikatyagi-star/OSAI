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

from agent.context import connector_context
from agent.hermes_client import run_via_hermes
from agent.orchestrator import run_ask
from api.schemas.agent import AskRequest
from db.models import Automation, User
from db.repositories import (
    create_automation,
    delete_automation,
    list_automations,
    list_documents_since,
    record_automation_run,
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
    """Run an automation now: execute its prompt through the agent and store the
    result. (Recurring execution on the cadence requires the Celery beat worker.)"""
    auto = db.get(Automation, automation_id)
    if auto is None or auto.org_id != org_id:
        raise HTTPException(status_code=404, detail="Automation not found.")

    # Resolve the acting user's identity + permissions so a per-user Hermes runs
    # in their isolated context and OSAI can scope any retrieval to their access.
    user_id = claims.get("sub") if claims else None
    permissions: list[str] = []
    if user_id:
        user = db.get(User, user_id)
        if user:
            permissions = list(user.permissions or [])

    # Run context: what's connected now, which sources were added since the last
    # run, and which documents arrived — so "summarize what's new" is answerable.
    connectors_now = await connector_context(org_id)
    current_names = [
        line.split(" ", 2)[1] for line in connectors_now.splitlines() if line.startswith("- ")
    ]
    added = [n for n in current_names if n not in (auto.last_connectors or [])]
    new_docs = list_documents_since(db, org_id, auto.last_run_at)
    doc_lines = [
        f"- [{source}] {title} ({ingested:%Y-%m-%d})" for source, title, ingested in new_docs
    ] or ["No new items."]
    run_context = "\n".join(
        [
            "Automation context:",
            connectors_now or "No data sources are connected yet.",
            "Connectors added since last run: " + (", ".join(added) if added else "none"),
            f"New items since last run ({auto.last_run_at or 'never'}):",
            *doc_lines,
        ]
    )

    # --- executor seam: per-user Hermes sidecar if configured, else in-house ---
    hermes = await run_via_hermes(
        auto.prompt, org_id, user_id=user_id, permissions=permissions,
        extra_context=run_context,
    )
    if hermes is not None:
        record_automation_run(db, automation_id, hermes, connectors=current_names)
        return {"id": automation_id, "result": hermes, "via": "hermes", "citations": []}
    resp = await run_ask(
        AskRequest(org_id=org_id, question=f"{run_context}\n\nTask: {auto.prompt}")
    )
    record_automation_run(db, automation_id, resp.answer, connectors=current_names)
    return {"id": automation_id, "result": resp.answer, "via": "osai", "citations": resp.citations}
