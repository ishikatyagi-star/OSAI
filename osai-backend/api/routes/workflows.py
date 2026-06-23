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
)
from db.session import get_db, get_org_id
from workflows.runner import run_action_item_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]


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
async def get_workflow(workflow_id: str, db: DbSession) -> dict:
    """Return a single workflow run with its action items."""
    run = try_db(
        "get_workflow_run",
        None,
        lambda: get_workflow_run(db, workflow_id),
    )
    if run is None:
        raise HTTPException(status_code=404, detail=f"Workflow run {workflow_id!r} not found")
    return run


@router.post("", response_model=WorkflowRunResponse)
async def create_workflow(
    request: WorkflowRunCreate, db: DbSession, org_id: OrgId
) -> WorkflowRunResponse:
    """Run Gemini action-item extraction and persist the result."""
    # Enforce the authenticated org from the JWT, not the request body.
    request.org_id = org_id
    run_id = f"workflow-{uuid4()}"
    response = await run_action_item_workflow(run_id=run_id, request=request, db=db)

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
