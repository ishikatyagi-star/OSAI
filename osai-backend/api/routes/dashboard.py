"""Live dashboard metrics — real aggregates over an org's ingested data."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from connectors.registry import HARD_DISABLED_CONNECTOR_KEYS
from db.models import (
    ActionItemRecord,
    Automation,
    DecisionRecord,
    Department,
    SourceDocumentRecord,
    SyncRun,
    User,
    WorkflowRun,
    now_utc,
    utc_iso,
)
from db.repositories import current_org_actor
from db.repositories import list_integrations as list_db_integrations
from db.session import get_db, get_optional_claims, get_org_id

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]


def _metrics(
    db: Session,
    org_id: str,
    *,
    viewer_user_id: str | None = None,
    viewer_is_admin: bool = False,
) -> dict:
    docs_by_connector = dict(
        db.query(SourceDocumentRecord.source_type, func.count())
        .filter(SourceDocumentRecord.org_id == org_id)
        .group_by(SourceDocumentRecord.source_type)
        .all()
    )
    docs_by_tier = dict(
        db.query(SourceDocumentRecord.data_tier, func.count())
        .filter(SourceDocumentRecord.org_id == org_id)
        .group_by(SourceDocumentRecord.data_tier)
        .all()
    )
    total_docs = sum(docs_by_connector.values())

    sync_total = db.query(func.count(SyncRun.id)).filter(SyncRun.org_id == org_id).scalar() or 0
    sync_ok = (
        db.query(func.count(SyncRun.id))
        .filter(SyncRun.org_id == org_id, SyncRun.status == "succeeded")
        .scalar()
        or 0
    )
    last_sync = (
        db.query(func.max(SyncRun.finished_at)).filter(SyncRun.org_id == org_id).scalar()
    )
    connector_statuses = [
        {
            "key": item["key"],
            "auth_state": item["auth_state"],
            "last_sync": item["last_sync"],
            "sync_error": item["sync_error"],
        }
        for item in list_db_integrations(db, org_id)
        if item["auth_state"] != "not_configured"
        and item["key"] not in HARD_DISABLED_CONNECTOR_KEYS
    ]
    connected = sum(item["auth_state"] == "connected" for item in connector_statuses)

    pending_decisions = (
        db.query(func.count(DecisionRecord.id))
        .filter(DecisionRecord.org_id == org_id, DecisionRecord.status == "proposed")
        .scalar()
        or 0
    )
    recent_decisions = (
        db.query(DecisionRecord)
        .filter(DecisionRecord.org_id == org_id)
        .order_by(DecisionRecord.decided_at.desc())
        .limit(4)
        .all()
    )

    pending_action_query = (
        db.query(func.count(ActionItemRecord.id))
        .join(WorkflowRun, WorkflowRun.id == ActionItemRecord.workflow_run_id)
        .filter(
            WorkflowRun.org_id == org_id,
            ActionItemRecord.status == "needs_review",
        )
    )
    if viewer_is_admin:
        pending_actions = pending_action_query.scalar() or 0
    elif viewer_user_id:
        pending_actions = (
            pending_action_query.filter(WorkflowRun.created_by == viewer_user_id).scalar() or 0
        )
    else:
        pending_actions = 0
    members = db.query(func.count(User.id)).filter(User.org_id == org_id).scalar() or 0
    departments = (
        db.query(func.count(Department.id)).filter(Department.org_id == org_id).scalar() or 0
    )
    automations = (
        db.query(func.count(Automation.id)).filter(Automation.org_id == org_id).scalar() or 0
    )

    return {
        "total_documents": total_docs,
        "documents_by_connector": {str(k): int(v) for k, v in docs_by_connector.items()},
        "documents_by_tier": {str(k): int(v) for k, v in docs_by_tier.items()},
        "connectors_connected": int(connected),
        "connector_statuses": connector_statuses,
        "pending_decisions": int(pending_decisions),
        "pending_actions": int(pending_actions),
        "recent_decisions": [
            {
                "id": decision.id,
                "title": decision.title,
                "status": decision.status,
                "owner": decision.owner,
                "date": utc_iso(decision.decided_at),
            }
            for decision in recent_decisions
        ],
        "sync_runs_total": int(sync_total),
        "sync_runs_succeeded": int(sync_ok),
        "last_sync_at": utc_iso(last_sync) if last_sync else None,
        "members": int(members),
        "departments": int(departments),
        "automations": int(automations),
    }


@router.get("/metrics")
async def metrics(db: DbSession, org_id: OrgId, claims: OptionalClaims) -> dict:
    """Live metrics aggregated from the org's real ingested data + workspace.

    A database failure must never be reported as zeros. "0 documents, 0 members"
    is not an error message — it reads as "your workspace is empty", i.e. data
    loss, when the truth is only that we could not reach the data. That matters
    concretely here: the free-tier database pauses when idle, so the failure mode
    is routine. Fail with 503 and let the client say so honestly (SHE-6 P1 "do
    not convert database/service failures to zero").

    Genuine zeros still return 200 — an empty workspace is a real answer.
    """
    try:
        actor_id, is_admin = current_org_actor(db, org_id, claims)
        data = _metrics(
            db,
            org_id,
            viewer_user_id=actor_id,
            viewer_is_admin=is_admin,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Metrics are unavailable: the workspace database could not be "
                "reached. Your data is not lost."
            ),
        ) from exc
    # Freshness (SHE-6 P1 "include freshness metadata"): every count above is
    # true as of this instant, so a client showing a cached or retried view can
    # say when it was true rather than implying it is live.
    return {**data, "as_of": utc_iso(now_utc())}
