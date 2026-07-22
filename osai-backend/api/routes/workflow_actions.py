"""Workflow action-item approval and execution endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.ratelimit import PROVIDER_ACTION_BUDGET, rate_limit
from api.schemas.connector import ConnectorAction
from config import settings
from connectors.registry import connector_registry
from db.repositories import (
    approve_action_item,
    cancel_action_item,
    claim_action_item,
    current_org_actor,
    get_workflow_run,
    try_db,
    update_action_item_execution,
    workflow_action_execution_key,
)
from db.session import get_db, get_optional_claims, require_writable_org

router = APIRouter(prefix="/workflows", tags=["workflow-actions"])
DbSession = Annotated[Session, Depends(get_db)]
# Approving an action item executes it against a connector — never from the
# anonymous demo workspace (SEC-003).
OrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]


def _authorize_run(
    run: dict,
    run_id: str,
    db: Session,
    caller_org_id: str,
    claims: dict | None,
) -> tuple[str, str]:
    """Bind workflow access to its creator or a current organization admin."""
    org_id = run.get("org_id", settings.default_org_id)
    if org_id != caller_org_id:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id!r} not found")
    actor_id, is_admin = current_org_actor(db, org_id, claims)
    if not is_admin and (not actor_id or run.get("created_by") != actor_id):
        # Rows created before ownership was persisted are deliberately admin-only.
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id!r} not found")
    assert actor_id is not None  # creator/admin authorization requires a principal
    return org_id, actor_id


@router.post(
    "/{run_id}/action-items/{item_id}/approve",
    dependencies=[Depends(rate_limit(*PROVIDER_ACTION_BUDGET))],
)
async def approve_item(
    run_id: str,
    item_id: str,
    db: DbSession,
    caller_org_id: OrgId,
    claims: OptionalClaims,
) -> dict:
    """Approve a needs_review action item and push it to its destination connector."""
    # 1. Fetch the workflow run to get org_id
    run = try_db("get_workflow_run", None, lambda: get_workflow_run(db, run_id))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id!r} not found")

    # Cross-tenant + resource-owner guard before exposing item state or claiming
    # a connector side effect.
    org_id, actor_id = _authorize_run(run, run_id, db, caller_org_id, claims)

    # 2. Find the action item in the run
    item_data = next((i for i in run.get("action_items", []) if i["id"] == item_id), None)
    if item_data is None:
        raise HTTPException(status_code=404, detail=f"Action item {item_id!r} not found")

    destination = item_data.get("destination", "manual")
    if destination != "manual":
        from llm.policy import connector_egress_allowed, load_data_routing

        routing = load_data_routing(org_id)
        if not connector_egress_allowed(
            routing,
            [run.get("data_tier")],
            destination,
        ):
            # Check before the atomic claim: a policy correction can make this
            # item approvable later, and no blocked request may consume it.
            raise HTTPException(
                status_code=403,
                detail="Delivery blocked by data-routing policy.",
            )

    connector = None
    if destination != "manual":
        try:
            connector = connector_registry.get(destination)
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Connector {destination!r} is not available.",
            ) from exc

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
        lambda: claim_action_item(db, item_id=item_id, org_id=org_id, actor=actor_id),
    )
    if claim != "claimed":
        current = try_db("get_workflow_run", None, lambda: get_workflow_run(db, run_id)) or {}
        latest = next((i for i in current.get("action_items", []) if i["id"] == item_id), item_data)
        return {
            "item_id": item_id,
            "status": latest.get("status", item_data["status"]),
            "message": "Item is already being handled or has been handled.",
        }

    try:
        approved = approve_action_item(
            db,
            item_id=item_id,
            org_id=org_id,
            actor=actor_id,
        )
        if approved is None:
            raise RuntimeError("Claimed action item disappeared before execution.")
    except Exception as exc:  # noqa: BLE001 - fail closed before provider dispatch
        db.rollback()
        try:
            update_action_item_execution(
                db,
                item_id=item_id,
                org_id=org_id,
                status="failed_preflight",
            )
        except Exception:  # noqa: BLE001 - executing still blocks provider replay
            db.rollback()
        raise HTTPException(
            status_code=503,
            detail="The action could not be prepared. It is safe to retry later.",
        ) from exc

    # 4. Attempt connector execution
    exec_status = "completed"
    external_url = None
    provider_may_have_run = False
    exec_message = "Destination is manual — no connector push needed."

    if destination != "manual":
        try:
            action = ConnectorAction(
                action_type=_action_type_for_destination(destination),
                payload=_build_payload(item_data, destination),
                idempotency_key=workflow_action_execution_key(item_id),
            )
            provider_may_have_run = True
            assert connector is not None
            result = await connector.execute_action(org_id, action)
            external_url = result.url
            if result.status == "succeeded":
                exec_status = "completed"
                exec_message = f"Pushed to {destination}"
            elif result.status == "skipped":
                provider_may_have_run = False
                exec_status = "failed_preflight"
                exec_message = result.error or "Connector is not ready; retry later."
            else:
                exec_status = "outcome_unknown"
                exec_message = "Provider outcome is unknown; reconcile before retrying."
        except Exception:  # noqa: BLE001 - timeout after dispatch is ambiguous
            exec_status = "outcome_unknown"
            exec_message = "Provider outcome is unknown; reconcile before retrying."

    # A failed commit acknowledgement after provider dispatch is ambiguous too.
    final_status = exec_status
    try:
        persisted = update_action_item_execution(
            db,
            item_id=item_id,
            org_id=org_id,
            status=final_status,
            external_url=external_url,
        )
    except Exception:  # noqa: BLE001 - database commit acknowledgement may be ambiguous
        db.rollback()
        persisted = False
    if not persisted:
        fallback_status = "outcome_unknown" if provider_may_have_run else "failed_preflight"
        try:
            update_action_item_execution(
                db,
                item_id=item_id,
                org_id=org_id,
                status=fallback_status,
            )
        except Exception:  # noqa: BLE001 - executing remains a durable no-retry state
            db.rollback()
        final_status = fallback_status
        exec_message = (
            "Provider outcome is unknown; reconcile before retrying."
            if provider_may_have_run
            else "Execution was not started; retry after the database recovers."
        )

    return {
        "item_id": item_id,
        "status": final_status,
        "destination": destination,
        "external_url": external_url,
        "message": exec_message,
        "reconciliation_required": final_status == "outcome_unknown",
    }


def _load_item(
    run_id: str,
    item_id: str,
    db: Session,
    caller_org_id: str,
    claims: dict | None,
) -> tuple[str, dict, str]:
    """Resolve an action item after tenant and creator/admin authorization."""
    run = try_db("get_workflow_run", None, lambda: get_workflow_run(db, run_id))
    if run is None:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id!r} not found")
    org_id, actor_id = _authorize_run(run, run_id, db, caller_org_id, claims)
    item = next((i for i in run.get("action_items", []) if i["id"] == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Action item {item_id!r} not found")
    return org_id, item, actor_id


@router.post("/{run_id}/action-items/{item_id}/cancel")
async def cancel_item(
    run_id: str,
    item_id: str,
    db: DbSession,
    caller_org_id: OrgId,
    claims: OptionalClaims,
) -> dict:
    """Reject an action item awaiting review so it stops asking to be run.

    `cancelled` is terminal: unlike `failed` it cannot be claimed again, so a
    rejected item can never be executed by a later approval."""
    org_id, _, actor_id = _load_item(run_id, item_id, db, caller_org_id, claims)
    outcome = try_db(
        "cancel_action_item",
        "taken",
        lambda: cancel_action_item(db, item_id=item_id, org_id=org_id, actor=actor_id),
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
