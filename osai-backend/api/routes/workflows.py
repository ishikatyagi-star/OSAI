from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.schemas.workflow_run import WorkflowRunCreate, WorkflowRunResponse
from config import settings
from db.repositories import (
    get_workflow_run as get_db_workflow_run,
)
from db.repositories import (
    list_action_items,
    list_workflow_runs,
    record_workflow_run,
    try_db,
)
from db.session import get_db
from workflows.runner import run_action_item_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("")
async def list_workflows(db: DbSession) -> list[dict[str, object]]:
    fallback = [
        {
            "id": "seed-workflow",
            "kind": "meeting_action_items",
            "status": "ready",
            "created_at": datetime.now(UTC).isoformat(),
            "model": "router:stub",
            "actions_created": 0,
        }
    ]
    return try_db(
        "list_workflows",
        fallback,
        lambda: [
            {
                "id": run.id,
                "kind": run.kind,
                "status": run.status,
                "created_at": run.created_at.isoformat(),
                "model": run.model_route or "router:unknown",
                "actions_created": len(list_action_items(db, run.id)),
            }
            for run in list_workflow_runs(db, settings.default_org_id)
        ]
        or fallback,
    )


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, db: DbSession) -> dict[str, object]:
    fallback = {
        "id": workflow_id,
        "kind": "meeting_action_items",
        "status": "ready",
        "items": [],
        "external_actions": [],
        "audit_events": [],
    }
    return try_db(
        "get_workflow",
        fallback,
        lambda: _serialize_workflow_detail(db, workflow_id) or fallback,
    )


@router.post("", response_model=WorkflowRunResponse)
async def create_workflow(request: WorkflowRunCreate, db: DbSession) -> WorkflowRunResponse:
    run_id = f"workflow-{uuid4()}"
    response = await run_action_item_workflow(run_id=run_id, request=request)
    try_db(
        "record_workflow_run",
        None,
        lambda: record_workflow_run(
            db,
            run_id=run_id,
            org_id=request.org_id,
            input_text=request.input_text,
            destination=request.destination,
            data_tier=request.data_tier,
            status=response.status,
            model_route=response.model_route,
            action_items=[item.model_dump() for item in response.action_items],
        ),
    )
    return response


def _serialize_workflow_detail(db: Session, workflow_id: str) -> dict[str, object] | None:
    workflow = get_db_workflow_run(db, workflow_id)
    if workflow is None:
        return None
    return {
        "id": workflow.id,
        "kind": workflow.kind,
        "status": workflow.status,
        "model": workflow.model_route,
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "owner": item.owner,
                "due_date": item.due_date.isoformat() if item.due_date else None,
                "destination": item.destination,
                "confidence": item.confidence / 100,
                "status": item.status,
            }
            for item in list_action_items(db, workflow_id)
        ],
        "external_actions": [],
        "audit_events": [],
    }
