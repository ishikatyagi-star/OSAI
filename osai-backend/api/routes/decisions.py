"""Org decision log CRUD — durable backend for the Decisions page."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models import DecisionRecord
from db.repositories import try_db
from db.session import get_db, get_org_id, require_writable_org
from memory.org_memory import record_memory

logger = logging.getLogger("osai.decisions")

router = APIRouter(prefix="/decisions", tags=["decisions"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]

_STATUSES = ("proposed", "approved", "rejected")
_IMPACTS = ("critical", "high", "medium", "low")


class DecisionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=2_000)
    status: str = "proposed"
    impact: str = "medium"
    owner: str | None = None
    source: str = "Manual"
    identified_by: str = "source"  # source | osai
    tags: list[str] | None = None


class DecisionUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    impact: str | None = None
    owner: str | None = None
    source: str | None = None
    tags: list[str] | None = None


def _validate(status: str | None, impact: str | None) -> None:
    if status is not None and status not in _STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {_STATUSES}.")
    if impact is not None and impact not in _IMPACTS:
        raise HTTPException(status_code=400, detail=f"impact must be one of {_IMPACTS}.")


def _serialize(d: DecisionRecord) -> dict:
    return {
        "id": d.id,
        "title": d.title,
        "status": d.status,
        "impact": d.impact,
        "owner": d.owner,
        "source": d.source,
        "identifiedBy": d.identified_by,
        "tags": d.tags or [],
        "date": d.decided_at.isoformat(),
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


@router.get("")
async def list_decisions(db: DbSession, org_id: OrgId) -> list[dict]:
    return try_db(
        "list_decisions",
        [],
        lambda: [
            _serialize(d)
            for d in db.query(DecisionRecord)
            .filter(DecisionRecord.org_id == org_id)
            .order_by(DecisionRecord.decided_at.desc())
            .all()
        ],
    )


@router.post("")
async def create_decision(body: DecisionCreate, db: DbSession, org_id: WriteOrgId) -> dict:
    _validate(body.status, body.impact)
    row = DecisionRecord(
        org_id=org_id,
        title=body.title.strip(),
        status=body.status,
        impact=body.impact,
        owner=(body.owner or "").strip() or None,
        source=body.source.strip() or "Manual",
        identified_by=body.identified_by if body.identified_by in ("source", "osai") else "source",
        tags=body.tags or None,
    )
    db.add(row)
    db.commit()

    # Real work feeds the org's memory: a logged decision becomes a fact Ask can
    # recall and cite (best-effort — never blocks decision creation).
    try:
        record_memory(
            db,
            org_id,
            kind="decision",
            content=f"Decision: {row.title} — status {row.status}, impact {row.impact}"
            + (f", owner {row.owner}" if row.owner else ""),
        )
    except Exception:  # noqa: BLE001 — memory is best-effort
        logger.warning("Could not record decision memory for %s", row.id)
    return _serialize(row)


@router.patch("/{decision_id}")
async def update_decision(
    decision_id: str, body: DecisionUpdate, db: DbSession, org_id: WriteOrgId
) -> dict:
    _validate(body.status, body.impact)
    row = db.get(DecisionRecord, decision_id)
    if row is None or row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Decision not found.")
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(status_code=400, detail="Title cannot be empty.")
        row.title = body.title.strip()
    if body.status is not None:
        row.status = body.status
    if body.impact is not None:
        row.impact = body.impact
    if body.owner is not None:
        row.owner = body.owner.strip() or None
    if body.source is not None:
        row.source = body.source.strip() or "Manual"
    if body.tags is not None:
        row.tags = body.tags
    db.commit()
    return _serialize(row)


@router.delete("/{decision_id}")
async def delete_decision(decision_id: str, db: DbSession, org_id: WriteOrgId) -> dict:
    row = db.get(DecisionRecord, decision_id)
    if row is None or row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Decision not found.")
    db.delete(row)
    db.commit()
    return {"deleted": True}
