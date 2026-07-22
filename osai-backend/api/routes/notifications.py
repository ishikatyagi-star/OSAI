"""Per-user in-app notifications (e.g. "X shared a file with you")."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from db.models import Notification, utc_iso
from db.session import get_db, get_optional_claims, get_org_id, require_writable_org

router = APIRouter(prefix="/notifications", tags=["notifications"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]


def _row(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "payload": n.payload or {},
        "read": n.read,
        "created_at": utc_iso(n.created_at),
    }


@router.get("")
async def list_notifications(
    db: DbSession, org_id: OrgId, claims: OptionalClaims, unread_only: bool = True
) -> list[dict]:
    user_id = claims.get("sub") if claims else None
    if not user_id:
        return []  # demo/unauthenticated context has no personal inbox
    q = db.query(Notification).filter(
        Notification.org_id == org_id, Notification.user_id == user_id
    )
    if unread_only:
        q = q.filter(Notification.read.is_(False))
    return [
        _row(n)
        for n in q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(50)
    ]


@router.get("/page")
async def paginated_notifications(
    db: DbSession,
    org_id: OrgId,
    claims: OptionalClaims,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, object]:
    """Return one stable page plus inbox-wide total and unread counts."""
    user_id = claims.get("sub") if claims else None
    if not user_id:
        return {"items": [], "next_cursor": None, "total": 0, "unread_count": 0}

    inbox = (Notification.org_id == org_id, Notification.user_id == user_id)
    stmt = select(Notification).where(*inbox)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    if cursor:
        boundary_stmt = select(Notification).where(*inbox, Notification.id == cursor)
        if unread_only:
            boundary_stmt = boundary_stmt.where(Notification.read.is_(False))
        boundary = db.scalar(boundary_stmt)
        if boundary is None:
            raise HTTPException(status_code=422, detail="Invalid notification cursor.")
        stmt = stmt.where(
            or_(
                Notification.created_at < boundary.created_at,
                and_(
                    Notification.created_at == boundary.created_at,
                    Notification.id < boundary.id,
                ),
            )
        )

    rows = list(
        db.scalars(
            stmt.order_by(desc(Notification.created_at), desc(Notification.id)).limit(limit + 1)
        ).all()
    )
    items = rows[:limit]
    total = db.scalar(select(func.count(Notification.id)).where(*inbox)) or 0
    unread_count = (
        db.scalar(select(func.count(Notification.id)).where(*inbox, Notification.read.is_(False)))
        or 0
    )
    return {
        "items": [_row(n) for n in items],
        "next_cursor": items[-1].id if len(rows) > limit else None,
        "total": int(total),
        "unread_count": int(unread_count),
    }


@router.post("/read-all")
async def mark_all_read(
    db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> dict[str, int]:
    user_id = claims.get("sub") if claims else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    updated = (
        db.query(Notification)
        .filter(
            Notification.org_id == org_id,
            Notification.user_id == user_id,
            Notification.read.is_(False),
        )
        .update({Notification.read: True}, synchronize_session="fetch")
    )
    db.commit()
    return {"updated": updated}


@router.post("/{notification_id}/read")
async def mark_read(
    db: DbSession, org_id: WriteOrgId, claims: OptionalClaims, notification_id: str
) -> dict:
    user_id = claims.get("sub") if claims else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    n = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.org_id == org_id,
            Notification.user_id == user_id,
        )
    )
    if n is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    n.read = True
    db.commit()
    return _row(n)
