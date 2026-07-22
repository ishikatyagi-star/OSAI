"""Saved artifacts — pinned answer outputs, reusable across conversations."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from api.schemas.agent import AskUiArtifact
from db.models import SavedArtifact, utc_iso
from db.repositories import current_org_actor
from db.session import get_db, get_optional_claims, get_org_id, require_writable_org

router = APIRouter(prefix="/artifacts", tags=["artifacts"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]


def _row(a: SavedArtifact) -> dict:
    return {
        "id": a.id,
        "thread_id": a.thread_id,
        "title": a.title,
        "kind": a.kind,
        "data": a.data or {},
        "created_by_name": a.created_by_name,
        "created_at": utc_iso(a.created_at) if a.created_at else None,
    }


def _actor(db: Session, org_id: str, claims: dict | None) -> tuple[str, bool]:
    user_id, is_admin = current_org_actor(db, org_id, claims)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user_id, is_admin


class ArtifactCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    kind: str | None = Field(default=None, max_length=50)
    data: AskUiArtifact
    thread_id: str | None = None


@router.post("")
async def save_artifact(
    body: ArtifactCreate, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> dict:
    user_id, _ = _actor(db, org_id, claims)
    a = SavedArtifact(
        org_id=org_id,
        thread_id=body.thread_id,
        title=body.title.strip(),
        kind=body.kind or body.data.kind,
        data=body.data.model_dump(mode="json"),
        created_by=user_id,
        created_by_name=claims.get("email") if claims else None,
    )
    db.add(a)
    db.commit()
    return _row(a)


@router.get("")
async def list_artifacts(db: DbSession, org_id: OrgId, claims: OptionalClaims) -> list[dict]:
    user_id, is_admin = current_org_actor(db, org_id, claims)
    if not user_id:
        return []
    query = db.query(SavedArtifact).filter(SavedArtifact.org_id == org_id)
    if not is_admin:
        query = query.filter(SavedArtifact.created_by == user_id)
    rows = query.order_by(SavedArtifact.created_at.desc(), SavedArtifact.id.desc()).limit(200).all()
    return [_row(a) for a in rows]


@router.get("/page")
async def paginated_artifacts(
    db: DbSession,
    org_id: OrgId,
    claims: OptionalClaims,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, object]:
    """Return one stable page from the current actor's visible artifacts."""
    user_id, is_admin = current_org_actor(db, org_id, claims)
    if not user_id:
        return {"items": [], "next_cursor": None, "total": 0}

    visible = db.query(SavedArtifact).filter(SavedArtifact.org_id == org_id)
    if not is_admin:
        visible = visible.filter(SavedArtifact.created_by == user_id)
    total = visible.count()

    query = visible
    if cursor:
        boundary = visible.filter(SavedArtifact.id == cursor).one_or_none()
        if boundary is None:
            raise HTTPException(status_code=422, detail="Invalid artifact cursor.")
        query = query.filter(
            or_(
                SavedArtifact.created_at < boundary.created_at,
                and_(
                    SavedArtifact.created_at == boundary.created_at,
                    SavedArtifact.id < boundary.id,
                ),
            )
        )

    rows = (
        query.order_by(SavedArtifact.created_at.desc(), SavedArtifact.id.desc())
        .limit(limit + 1)
        .all()
    )
    items = rows[:limit]
    next_cursor = items[-1].id if len(rows) > limit else None
    return {
        "items": [_row(artifact) for artifact in items],
        "next_cursor": next_cursor,
        "total": total,
    }


@router.delete("/{artifact_id}")
async def delete_artifact(
    db: DbSession, org_id: WriteOrgId, claims: OptionalClaims, artifact_id: str
) -> dict:
    user_id, is_admin = _actor(db, org_id, claims)
    query = db.query(SavedArtifact).filter(
        SavedArtifact.id == artifact_id,
        SavedArtifact.org_id == org_id,
    )
    if not is_admin:
        query = query.filter(SavedArtifact.created_by == user_id)
    query.delete(synchronize_session=False)
    db.commit()
    # DELETE is deliberately terminal and retry-safe. A missing or unauthorized
    # ID returns the same result without revealing whether another member owns it.
    return {"deleted": True}
