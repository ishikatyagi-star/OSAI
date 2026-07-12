"""Automations — natural-language tasks that run on a cadence or on demand.

The executor is intentionally a thin seam: `_run` calls OSAI's in-house agent
(`run_ask`) today, and can be repointed at a Hermes sidecar later without
changing the API or UI.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.automation_runner import execute_automation
from db.models import Automation, User
from db.repositories import (
    UNSET,
    create_automation,
    delete_automation,
    list_automations,
    update_automation,
)
from db.session import get_db, get_optional_claims, get_org_id

router = APIRouter(prefix="/automations", tags=["automations"])
# Separate router for the tokened external trigger — mounted without the
# org-auth dependency chain the main router's routes resolve per-call.
trigger_router = APIRouter(prefix="/automations", tags=["automations"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

VALID_CADENCES = ("manual", "hourly", "daily", "weekly")
VALID_STATUSES = ("draft", "active", "paused")
VALID_DELIVERY_CHANNELS = ("slack",)


def _validated_delivery(deliver_to: dict | None) -> dict | None:
    """Normalize/validate a delivery target. None or {} clears delivery."""
    if not deliver_to:
        return None
    channel = str(deliver_to.get("channel", "")).lower()
    target = str(deliver_to.get("target", "")).strip()
    if channel not in VALID_DELIVERY_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"delivery channel must be one of {VALID_DELIVERY_CHANNELS}.",
        )
    if not target:
        raise HTTPException(status_code=400, detail="Delivery target is required.")
    return {"channel": channel, "target": target}


class AutomationCreate(BaseModel):
    name: str
    prompt: str
    cadence: str = "manual"
    status: str = "active"
    deliver_to: dict | None = None


class AutomationUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    cadence: str | None = None
    enabled: bool | None = None
    status: str | None = None
    # None = leave unchanged; {} = clear delivery; {channel, target} = set.
    deliver_to: dict | None = None


def _serialize(a: Automation) -> dict[str, object]:
    return {
        "id": a.id,
        "name": a.name,
        "prompt": a.prompt,
        "cadence": a.cadence,
        "enabled": a.enabled,
        # Legacy rows may predate `status`; enabled=False reads as paused.
        "status": (a.status or "active") if a.enabled else "paused",
        "last_run_at": a.last_run_at.isoformat() if a.last_run_at else None,
        "last_result": a.last_result,
        "deliver_to": a.deliver_to,
        "last_delivery": a.last_delivery,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        # External trigger API: token is shown once at mint time, never here.
        "has_trigger_token": bool(a.trigger_token_hash),
    }


@router.get("")
async def list_(db: DbSession, org_id: OrgId) -> list[dict[str, object]]:
    return [_serialize(a) for a in list_automations(db, org_id)]


@router.post("")
async def create_(body: AutomationCreate, db: DbSession, org_id: OrgId) -> dict[str, object]:
    if not body.name.strip() or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Name and prompt are required.")
    cadence = body.cadence if body.cadence in VALID_CADENCES else "manual"
    status = body.status if body.status in VALID_STATUSES else "active"
    a = create_automation(
        db, org_id=org_id, user_id=None, name=body.name.strip(),
        prompt=body.prompt.strip(), cadence=cadence, status=status,
        deliver_to=_validated_delivery(body.deliver_to),
    )
    return _serialize(a)


@router.patch("/{automation_id}")
async def update_(
    automation_id: str, body: AutomationUpdate, db: DbSession, org_id: OrgId
) -> dict[str, object]:
    if body.cadence is not None and body.cadence not in VALID_CADENCES:
        raise HTTPException(status_code=400, detail=f"cadence must be one of {VALID_CADENCES}.")
    if body.status is not None and body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}.")
    if body.name is not None and not body.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty.")
    if body.prompt is not None and not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
    a = update_automation(
        db, org_id, automation_id,
        name=body.name.strip() if body.name else None,
        prompt=body.prompt.strip() if body.prompt else None,
        cadence=body.cadence, enabled=body.enabled, status=body.status,
        # Distinguish "not sent" (leave as-is) from {} (clear) and a dict (set).
        deliver_to=(
            UNSET if body.deliver_to is None else _validated_delivery(body.deliver_to)
        ),
    )
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found.")
    return _serialize(a)


@router.delete("/{automation_id}")
async def delete_(automation_id: str, db: DbSession, org_id: OrgId) -> dict[str, object]:
    if not delete_automation(db, org_id, automation_id):
        raise HTTPException(status_code=404, detail="Automation not found.")
    return {"deleted": True}


@router.post("/{automation_id}/run")
async def run_(
    automation_id: str, db: DbSession, org_id: OrgId, claims: OptionalClaims
) -> dict[str, object]:
    """Run an automation now through the shared runner (the Celery beat scheduler
    uses the same runner, so manual and scheduled runs behave identically)."""
    auto = db.get(Automation, automation_id)
    if auto is None or auto.org_id != org_id:
        raise HTTPException(status_code=404, detail="Automation not found.")

    # Resolve the acting user's identity + permissions so a per-user Hermes runs
    # in their isolated context and OSAI can scope any retrieval to their access.
    user_id = claims.get("sub") if claims else None
    permissions: list[str] | None = None
    if user_id:
        user = db.get(User, user_id)
        if user:
            permissions = list(user.permissions or [])

    return await execute_automation(db, auto, user_id=user_id, permissions=permissions)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/{automation_id}/token")
async def mint_trigger_token(
    automation_id: str, db: DbSession, org_id: OrgId
) -> dict[str, object]:
    """Mint (or rotate) the external trigger token for one automation. The
    plaintext is returned exactly once; only its hash is stored."""
    auto = db.get(Automation, automation_id)
    if auto is None or auto.org_id != org_id:
        raise HTTPException(status_code=404, detail="Automation not found.")
    token = f"osak_{secrets.token_urlsafe(32)}"
    auto.trigger_token_hash = _hash_token(token)
    db.commit()
    return {
        "token": token,
        "trigger_url": f"/automations/{auto.id}/trigger",
        "note": "Store this token now — it is not shown again.",
    }


@router.delete("/{automation_id}/token")
async def revoke_trigger_token(
    automation_id: str, db: DbSession, org_id: OrgId
) -> dict[str, object]:
    auto = db.get(Automation, automation_id)
    if auto is None or auto.org_id != org_id:
        raise HTTPException(status_code=404, detail="Automation not found.")
    auto.trigger_token_hash = None
    db.commit()
    return {"revoked": True}


# NOTE: no OrgId dependency — external callers authenticate with the scoped
# trigger token alone (PromptQL "Program API" equivalent). The token maps to
# exactly one automation in one org; a mismatch is a plain 401.
@trigger_router.post("/{automation_id}/trigger")
async def trigger_automation(
    automation_id: str,
    db: DbSession,
    x_trigger_token: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    auto = db.get(Automation, automation_id)
    if (
        auto is None
        or not auto.trigger_token_hash
        or not x_trigger_token
        or not secrets.compare_digest(auto.trigger_token_hash, _hash_token(x_trigger_token))
    ):
        raise HTTPException(status_code=401, detail="Invalid trigger token.")
    if not auto.enabled or (auto.status or "active") == "paused":
        raise HTTPException(status_code=409, detail="Automation is paused.")
    return await execute_automation(db, auto, user_id=None, permissions=None)
