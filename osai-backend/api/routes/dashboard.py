"""Live dashboard metrics — real aggregates over an org's ingested data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.models import (
    Automation,
    ConnectorAccount,
    Department,
    SourceDocumentRecord,
    SyncRun,
    User,
)
from db.session import get_db, get_org_id

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]


def _metrics(db: Session, org_id: str) -> dict:
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
    connected = (
        db.query(func.count(ConnectorAccount.id))
        .filter(ConnectorAccount.org_id == org_id, ConnectorAccount.auth_state == "connected")
        .scalar()
        or 0
    )
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
        "sync_runs_total": int(sync_total),
        "sync_runs_succeeded": int(sync_ok),
        "last_sync_at": last_sync.isoformat() if last_sync else None,
        "members": int(members),
        "departments": int(departments),
        "automations": int(automations),
    }


@router.get("/metrics")
async def metrics(db: DbSession, org_id: OrgId) -> dict:
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
        data = _metrics(db, org_id)
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
    return {**data, "as_of": datetime.now(UTC).isoformat()}
