"""Workflow action-item approval and execution endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas.connector import ConnectorAction
from config import settings
from connectors.registry import connector_registry
from db.repositories import (
    approve_action_item,
    get_workflow_run,
    try_db,
    update_action_item_execution,
)
from db.session import get_db, get_org_id

router = APIRouter(prefix="/workflows", tags=["workflow-actions"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]


@router.post("/{run_id}/action-items/{item_id}/approve")
async def approve_item(
    run_id: str, item_id: str, db: DbSession, caller_org_id: OrgId
) -> dict:
    """Approve a needs_review action item and push it to its destination connector."""
    # 1. Fetch the workflow run to get org_id
    run = try_db("get_workflow_run", None, lambda: get_workflow_run(db, run_id))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id!r} not found")

    org_id = run.get("org_id", settings.default_org_id)
    # Cross-tenant guard: this endpoint executes real connector actions
    # (Freshdesk/Slack/Notion), so refuse a run that belongs to another org.
    if org_id != caller_org_id:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id!r} not found")

    # 2. Find the action item in the run
    item_data = next((i for i in run.get("action_items", []) if i["id"] == item_id), None)
    if item_data is None:
        raise HTTPException(status_code=404, detail=f"Action item {item_id!r} not found")

    if item_data["status"] not in ("needs_review", "failed"):
        return {
            "item_id": item_id,
            "status": item_data["status"],
            "message": "Item is already approved or executed.",
        }

    # 3. Mark as approved in DB
    def _do_approve():
        return approve_action_item(db, item_id=item_id, org_id=org_id)

    try_db("approve_action_item", None, _do_approve)

    # 4. Attempt connector execution
    destination = item_data.get("destination", "manual")
    exec_status = "skipped"
    external_url = None
    exec_message = "Destination is manual — no connector push needed."

    if destination != "manual":
        try:
            connector = connector_registry.get(destination)
            action = ConnectorAction(
                action_type=_action_type_for_destination(destination),
                payload=_build_payload(item_data, destination),
            )
            result = await connector.execute_action(org_id, action)
            exec_status = result.status
            external_url = result.url
            exec_message = result.error or f"Pushed to {destination}"
        except KeyError:
            exec_status = "skipped"
            exec_message = f"Connector {destination!r} not found in registry"
        except Exception as exc:  # noqa: BLE001
            exec_status = "failed"
            exec_message = str(exc)

    # 5. Record execution outcome
    final_status = "executed" if exec_status == "succeeded" else exec_status
    try_db(
        "update_action_item_execution",
        None,
        lambda: update_action_item_execution(
            db, item_id=item_id, status=final_status, external_url=external_url
        ),
    )

    return {
        "item_id": item_id,
        "status": final_status,
        "destination": destination,
        "external_url": external_url,
        "message": exec_message,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action_type_for_destination(destination: str) -> str:
    mapping = {
        "freshdesk": "create_ticket",
        "slack": "post_message",
        "notion": "create_page",
    }
    return mapping.get(destination, "create_item")


def _build_payload(item: dict, destination: str) -> dict:
    title = item.get("title", "Action Item")
    owner = item.get("owner", "")
    source_quote = item.get("source_quote", "")
    description = f"{source_quote}\n\nOwner: {owner}" if owner else source_quote

    if destination == "freshdesk":
        return {
            "subject": title,
            "description": description,
            "priority": 2,
            "status": 2,
        }
    if destination == "slack":
        return {
            "channel": "general",
            "text": f"*Action Item:* {title}\n{description}",
        }
    # notion / default
    return {"title": title, "description": description}
