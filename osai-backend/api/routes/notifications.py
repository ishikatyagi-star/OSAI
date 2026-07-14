"""Per-user in-app notifications (e.g. "X shared a file with you")."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.models import Notification
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
        "created_at": n.created_at.isoformat() if n.created_at else None,
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
    return [_row(n) for n in q.order_by(Notification.created_at.desc()).limit(50)]


@router.post("/{notification_id}/read")
async def mark_read(
    db: DbSession, org_id: WriteOrgId, claims: OptionalClaims, notification_id: str
) -> dict:
    user_id = claims.get("sub") if claims else None
    n = db.get(Notification, notification_id)
    if n is None or n.org_id != org_id or (user_id and n.user_id != user_id):
        raise HTTPException(status_code=404, detail="Notification not found.")
    n.read = True
    db.commit()
    return _row(n)
