from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models import DecisionRecord
from db.session import get_db, get_org_id

router = APIRouter(prefix="/decisions", tags=["decisions"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
DecisionStatus = Literal["proposed", "approved", "rejected"]
DecisionImpact = Literal["critical", "high", "medium", "low"]


class DecisionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    status: DecisionStatus = "proposed"
    impact: DecisionImpact = "medium"
    owner: str = Field(default="Unassigned", max_length=200)
    source: str = Field(default="Manual", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)
    identified_by: Literal["source", "osai"] = "source"


class DecisionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    status: DecisionStatus | None = None
    impact: DecisionImpact | None = None
    owner: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=200)
    tags: list[str] | None = Field(default=None, max_length=20)


def _serialize(decision: DecisionRecord) -> dict[str, object]:
    return {
        "id": decision.id,
        "title": decision.title,
        "status": decision.status,
        "impact": decision.impact,
        "owner": decision.owner,
        "source": decision.source,
        "tags": decision.tags or [],
        "identified_by": decision.identified_by,
        "created_at": decision.created_at.isoformat(),
        "updated_at": decision.updated_at.isoformat(),
    }


@router.get("")
async def list_decisions(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    rows = (
        db.query(DecisionRecord)
        .filter(DecisionRecord.org_id == org_id)
        .order_by(DecisionRecord.created_at.desc())
        .all()
    )
    return [_serialize(row) for row in rows]


@router.post("", status_code=201)
async def create_decision(body: DecisionCreate, db: DbSession, org_id: OrgId) -> dict[str, object]:
    decision = DecisionRecord(
        org_id=org_id,
        title=body.title.strip(),
        status=body.status,
        impact=body.impact,
        owner=body.owner.strip() or "Unassigned",
        source=body.source.strip() or "Manual",
        tags=[tag.strip().lower() for tag in body.tags if tag.strip()],
        identified_by=body.identified_by,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return _serialize(decision)


@router.patch("/{decision_id}")
async def update_decision(
    decision_id: str, body: DecisionUpdate, db: DbSession, org_id: OrgId
) -> dict[str, object]:
    decision = db.get(DecisionRecord, decision_id)
    if decision is None or decision.org_id != org_id:
        raise HTTPException(status_code=404, detail="Decision not found")
    for field, value in body.model_dump(exclude_none=True).items():
        if isinstance(value, str):
            value = value.strip()
        if field == "tags":
            value = [tag.strip().lower() for tag in value if tag.strip()]
        setattr(decision, field, value)
    db.commit()
    db.refresh(decision)
    return _serialize(decision)


@router.delete("/{decision_id}")
async def delete_decision(decision_id: str, db: DbSession, org_id: OrgId) -> dict[str, bool]:
    decision = db.get(DecisionRecord, decision_id)
    if decision is None or decision.org_id != org_id:
        raise HTTPException(status_code=404, detail="Decision not found")
    db.delete(decision)
    db.commit()
    return {"deleted": True}
