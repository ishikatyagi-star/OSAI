"""Saved artifacts — pinned answer outputs, reusable across conversations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models import SavedArtifact
from db.session import get_db, get_optional_claims, get_org_id

router = APIRouter(prefix="/artifacts", tags=["artifacts"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]


def _row(a: SavedArtifact) -> dict:
    return {
        "id": a.id,
        "thread_id": a.thread_id,
        "title": a.title,
        "kind": a.kind,
        "data": a.data or {},
        "created_by_name": a.created_by_name,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


class ArtifactCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    kind: str = Field(default="answer_summary", max_length=50)
    data: dict = Field(default_factory=dict)
    thread_id: str | None = None


@router.post("")
async def save_artifact(
    body: ArtifactCreate, db: DbSession, org_id: OrgId, claims: OptionalClaims
) -> dict:
    a = SavedArtifact(
        org_id=org_id,
        thread_id=body.thread_id,
        title=body.title.strip(),
        kind=body.kind,
        data=body.data,
        created_by=claims.get("sub") if claims else None,
        created_by_name=claims.get("email") if claims else None,
    )
    db.add(a)
    db.commit()
    return _row(a)


@router.get("")
async def list_artifacts(db: DbSession, org_id: OrgId) -> list[dict]:
    rows = (
        db.query(SavedArtifact)
        .filter(SavedArtifact.org_id == org_id)
        .order_by(SavedArtifact.created_at.desc())
        .limit(200)
        .all()
    )
    return [_row(a) for a in rows]


@router.delete("/{artifact_id}")
async def delete_artifact(db: DbSession, org_id: OrgId, artifact_id: str) -> dict:
    a = db.get(SavedArtifact, artifact_id)
    if a is None or a.org_id != org_id:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    db.delete(a)
    db.commit()
    return {"deleted": True}
