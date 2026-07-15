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
    cancel_action_item,
    claim_action_item,
    get_workflow_run,
    try_db,
    update_action_item_execution,
)
from db.session import get_db, require_writable_org

router = APIRouter(prefix="/workflows", tags=["workflow-actions"])
DbSession = Annotated[Session, Depends(get_db)]
# Approving an action item executes it against a connector — never from the
# anonymous demo workspace (SEC-003).
OrgId = Annotated[str, Depends(require_writable_org)]


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

    # 3. Claim the item atomically. item_data above is a snapshot read before
    #    this request did anything, so checking its status cannot prevent a
    #    concurrent approval — two callers would both see needs_review, both
    #    proceed, and both push to the connector (duplicate ticket/message).
    #    Exactly one caller wins the claim; the loser returns the current state
    #    without executing (SHE-6 P0 "duplicate approval requests must not
    #    execute twice", same guarantee as the Ask confirm path in SEC-007).
    claim = try_db(
        "claim_action_item",
        "absent",
        lambda: claim_action_item(db, item_id=item_id, org_id=org_id),
    )
    if claim != "claimed":
        current = try_db("get_workflow_run", None, lambda: get_workflow_run(db, run_id)) or {}
        latest = next(
            (i for i in current.get("action_items", []) if i["id"] == item_id), item_data
        )
        return {
            "item_id": item_id,
            "status": latest.get("status", item_data["status"]),
            "message": "Item is already being handled or has been handled.",
        }

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

    # 5. Record execution outcome. "completed" is the terminal success state;
    #    "failed" stays claimable so a transient connector error can be retried.
    final_status = "completed" if exec_status == "succeeded" else exec_status
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


def _load_item(run_id: str, item_id: str, db: Session, caller_org_id: str) -> tuple[str, dict]:
    """Resolve an action item within a run, enforcing the cross-tenant guard."""
    run = try_db("get_workflow_run", None, lambda: get_workflow_run(db, run_id))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id!r} not found")
    org_id = run.get("org_id", settings.default_org_id)
    if org_id != caller_org_id:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id!r} not found")
    item = next((i for i in run.get("action_items", []) if i["id"] == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Action item {item_id!r} not found")
    return org_id, item


@router.post("/{run_id}/action-items/{item_id}/cancel")
async def cancel_item(
    run_id: str, item_id: str, db: DbSession, caller_org_id: OrgId
) -> dict:
    """Reject an action item awaiting review so it stops asking to be run.

    `cancelled` is terminal: unlike `failed` it cannot be claimed again, so a
    rejected item can never be executed by a later approval."""
    org_id, _ = _load_item(run_id, item_id, db, caller_org_id)
    outcome = try_db(
        "cancel_action_item",
        "taken",
        lambda: cancel_action_item(db, item_id=item_id, org_id=org_id),
    )
    if outcome != "cancelled":
        return {
            "item_id": item_id,
            "status": "taken",
            "message": "Item is already being handled or has been handled.",
        }
    return {"item_id": item_id, "status": "cancelled", "message": "Item cancelled."}


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
