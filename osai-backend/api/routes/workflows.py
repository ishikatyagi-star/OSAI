"""Workflow routes — Gemini extraction with DB persistence and approval flow."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas.workflow_run import WorkflowRunCreate, WorkflowRunResponse
from db.repositories import (
    get_workflow_run,
    list_workflow_runs,
    save_workflow_run,
    try_db,
    user_clearance,
    user_permissions,
)
from db.session import get_db, get_optional_claims, get_org_id, require_writable_org
from workflows.runner import run_action_item_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Creating a run spends LLM budget and persists org data — not from demo (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]


@router.get("")
async def list_workflows(db: DbSession, org_id: OrgId) -> list[dict]:
    """Return all workflow runs for the default org."""
    fallback: list[dict] = []
    return try_db(
        "list_workflows",
        fallback,
        lambda: [
            {
                "id": run.id,
                "kind": run.kind,
                "status": run.status,
                "destination": run.destination,
                "model_route": run.model_route,
                "created_at": run.created_at.isoformat(),
            }
            for run in list_workflow_runs(db, org_id)
        ],
    )


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, db: DbSession, org_id: OrgId) -> dict:
    """Return a single workflow run with its action items (caller's org only).

    Runs contain meeting transcripts and extracted action items, so this must
    never be readable by ID alone — 404 (not 403) on an org mismatch so the
    response doesn't confirm the ID exists in another workspace.
    """
    run = try_db(
        "get_workflow_run",
        None,
        lambda: get_workflow_run(db, workflow_id),
    )
    if run is None or run.get("org_id") != org_id:
        raise HTTPException(status_code=404, detail=f"Workflow run {workflow_id!r} not found")
    return run


@router.post("", response_model=WorkflowRunResponse)
async def create_workflow(
    request: WorkflowRunCreate, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> WorkflowRunResponse:
    """Run Gemini action-item extraction and persist the result."""
    # Bind the run to the caller's session org, ignoring any body-supplied org_id.
    request.org_id = org_id
    run_id = f"workflow-{uuid4()}"
    # Enrichment context is scoped to the initiating user's permissions/tier so
    # the extraction prompt can't become a side-door around retrieval ACLs.
    response = await run_action_item_workflow(
        run_id=run_id,
        request=request,
        db=db,
        requester_permissions=user_permissions(db, claims),
        requester_tier=user_clearance(db, claims),
    )

    # Persist to DB (best-effort; don't fail the response if DB is unavailable)
    try_db(
        "save_workflow_run",
        None,
        lambda: save_workflow_run(
            db,
            run_id=run_id,
            org_id=request.org_id,
            kind="meeting_action_items",
            status=response.status,
            input_text=request.input_text,
            destination=request.destination,
            data_tier=request.data_tier,
            model_route=response.model_route,
            items=[
                {
                    "title": item.title,
                    "owner": item.owner,
                    "due_date": item.due_date,
                    "source_quote": item.source_quote,
                    "destination": item.destination,
                    "confidence": item.confidence,
                }
                for item in response.action_items
            ],
        ),
    )
    return response
