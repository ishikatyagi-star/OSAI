"""Automations — natural-language tasks that run on a cadence or on demand.

The executor is intentionally a thin seam: `_run` calls OSAI's in-house agent
(`run_ask`) today, and can be repointed at a Hermes sidecar later without
changing the API or UI.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from agent.automation_runner import execute_automation
from api.ratelimit import (
    PROVIDER_ACTION_BUDGET,
    WORKFLOW_RUN_BUDGET,
    enforce_rate_limit,
    rate_limit,
)
from db.models import Automation, User, utc_iso
from db.repositories import (
    UNSET,
    create_automation,
    delete_automation,
    finish_automation_trigger,
    list_automations,
    reserve_automation_trigger,
    update_automation,
)
from db.session import (
    assert_writable_org,
    get_db,
    get_optional_claims,
    get_org_id,
    require_writable_org,
)

router = APIRouter(prefix="/automations", tags=["automations"])
# Separate router for the tokened external trigger — mounted without the
# org-auth dependency chain the main router's routes resolve per-call.
trigger_router = APIRouter(prefix="/automations", tags=["automations"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Automation writes schedule LLM runs, external delivery, and trigger tokens —
# not from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

VALID_CADENCES = ("manual", "hourly", "daily", "weekly")
VALID_STATUSES = ("draft", "active", "paused")
VALID_DELIVERY_CHANNELS = ("slack",)
MAX_TRIGGER_PAYLOAD_BYTES = 64 * 1024
MAX_AUTOMATION_NAME_CHARS = 200
MAX_AUTOMATION_PROMPT_CHARS = 20_000
MAX_DELIVERY_TARGET_CHARS = 200


def _validated_idempotency_request(
    idempotency_key: str | None,
    body: dict[str, object] | None,
) -> tuple[str, str]:
    key = idempotency_key or ""
    if (
        not 8 <= len(key) <= 128
        or key.strip() != key
        or not key.isascii()
        or any(ord(char) < 33 or ord(char) > 126 for char in key)
    ):
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must be 8-128 printable ASCII characters.",
        )
    encoded = json.dumps(
        body or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    if len(encoded) > MAX_TRIGGER_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Trigger payload is too large.")
    return key, hashlib.sha256(encoded).hexdigest()


async def get_scheduler_available() -> bool:
    """Injectable, fail-closed scheduler capability used by write routes."""
    from workers.scheduler_health import scheduler_available

    return await asyncio.to_thread(scheduler_available)


SchedulerAvailable = Annotated[bool, Depends(get_scheduler_available)]


def _require_supported_cadence(cadence: str, scheduler_available: bool) -> None:
    if cadence not in VALID_CADENCES:
        raise HTTPException(
            status_code=400,
            detail=f"cadence must be one of {VALID_CADENCES}.",
        )
    if cadence != "manual" and not scheduler_available:
        raise HTTPException(
            status_code=503,
            detail=(
                "Recurring automations are unavailable until the scheduler "
                "heartbeat is healthy. Choose manual cadence or try again later."
            ),
        )


class DeliveryTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Both fields are optional only so `{}` can retain its PATCH meaning: clear.
    channel: str | None = Field(default=None, max_length=32, strict=True)
    target: str | None = Field(default=None, max_length=MAX_DELIVERY_TARGET_CHARS, strict=True)


def _validated_delivery(deliver_to: DeliveryTarget | None) -> dict | None:
    """Normalize/validate a delivery target. None or {} clears delivery."""
    if deliver_to is None or (deliver_to.channel is None and deliver_to.target is None):
        return None
    channel = (deliver_to.channel or "").lower()
    target = (deliver_to.target or "").strip()
    if channel not in VALID_DELIVERY_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"delivery channel must be one of {VALID_DELIVERY_CHANNELS}.",
        )
    if not target:
        raise HTTPException(status_code=400, detail="Delivery target is required.")
    return {"channel": channel, "target": target}


class AutomationCreate(BaseModel):
    name: str = Field(max_length=MAX_AUTOMATION_NAME_CHARS, strict=True)
    # Leaves room for bounded run context inside AskRequest's 40k boundary.
    prompt: str = Field(max_length=MAX_AUTOMATION_PROMPT_CHARS, strict=True)
    cadence: str = Field(default="manual", max_length=16, strict=True)
    status: str = Field(default="active", max_length=16, strict=True)
    deliver_to: DeliveryTarget | None = None


class AutomationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_AUTOMATION_NAME_CHARS, strict=True)
    prompt: str | None = Field(default=None, max_length=MAX_AUTOMATION_PROMPT_CHARS, strict=True)
    cadence: str | None = Field(default=None, max_length=16, strict=True)
    enabled: bool | None = None
    status: str | None = Field(default=None, max_length=16, strict=True)
    # None = leave unchanged; {} = clear delivery; {channel, target} = set.
    deliver_to: DeliveryTarget | None = None


def _serialize(a: Automation) -> dict[str, object]:
    return {
        "id": a.id,
        "name": a.name,
        "prompt": a.prompt,
        "cadence": a.cadence,
        "enabled": a.enabled,
        # Legacy rows may predate `status`; enabled=False reads as paused.
        "status": (a.status or "active") if a.enabled else "paused",
        "last_run_at": utc_iso(a.last_run_at) if a.last_run_at else None,
        "last_result": a.last_result,
        "deliver_to": a.deliver_to,
        "last_delivery": a.last_delivery,
        "updated_at": utc_iso(a.updated_at) if a.updated_at else None,
        # External trigger API: token is shown once at mint time, never here.
        "has_trigger_token": bool(a.trigger_token_hash),
    }


def _current_user(db: Session, org_id: str, claims: dict | None) -> User:
    """Resolve the current principal from the database, never JWT role data."""
    user_id = claims.get("sub") if claims else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Session is no longer valid.")
    if user.org_id != org_id:
        # Conceal tenant resource membership if auth dependencies ever disagree.
        raise HTTPException(status_code=404, detail="Automation not found.")
    return user


def _authorized_automation(db: Session, org_id: str, automation_id: str, user: User) -> Automation:
    """Return an automation only to its current creator.

    Running, editing, deleting, or minting a trigger for another user's row
    would execute with that owner's private grants. Workspace admin status is
    therefore not an impersonation capability for automations.
    """
    auto = db.get(Automation, automation_id)
    if auto is None or auto.org_id != org_id or auto.user_id != user.id:
        raise HTTPException(status_code=404, detail="Automation not found.")
    return auto


@router.get("")
async def list_(db: DbSession, org_id: OrgId, claims: OptionalClaims) -> list[dict[str, object]]:
    user = _current_user(db, org_id, claims)
    rows = list_automations(db, org_id)
    rows = [auto for auto in rows if auto.user_id == user.id]
    return [_serialize(a) for a in rows]


@router.post("")
async def create_(
    body: AutomationCreate,
    db: DbSession,
    org_id: WriteOrgId,
    claims: OptionalClaims,
    scheduler_available: SchedulerAvailable,
) -> dict[str, object]:
    if not body.name.strip() or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Name and prompt are required.")
    _require_supported_cadence(body.cadence, scheduler_available)
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}.")
    delivery = _validated_delivery(body.deliver_to)
    user = _current_user(db, org_id, claims)
    a = create_automation(
        db,
        org_id=org_id,
        user_id=user.id,
        name=body.name.strip(),
        prompt=body.prompt.strip(),
        cadence=body.cadence,
        status=body.status,
        deliver_to=delivery,
    )
    return _serialize(a)


@router.patch("/{automation_id}")
async def update_(
    automation_id: str,
    body: AutomationUpdate,
    db: DbSession,
    org_id: WriteOrgId,
    claims: OptionalClaims,
    scheduler_available: SchedulerAvailable,
) -> dict[str, object]:
    if body.cadence is not None and body.cadence not in VALID_CADENCES:
        raise HTTPException(status_code=400, detail=f"cadence must be one of {VALID_CADENCES}.")
    if body.status is not None and body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}.")
    if body.name is not None and not body.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty.")
    if body.prompt is not None and not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
    user = _current_user(db, org_id, claims)
    current = _authorized_automation(db, org_id, automation_id, user)
    cadence_being_activated = (
        body.cadence is not None or body.enabled is True or body.status == "active"
    )
    if cadence_being_activated:
        _require_supported_cadence(
            body.cadence if body.cadence is not None else current.cadence,
            scheduler_available,
        )
    a = update_automation(
        db,
        org_id,
        automation_id,
        name=body.name.strip() if body.name else None,
        prompt=body.prompt.strip() if body.prompt else None,
        cadence=body.cadence,
        enabled=body.enabled,
        status=body.status,
        # Distinguish "not sent" (leave as-is) from {} (clear) and a dict (set).
        deliver_to=(UNSET if body.deliver_to is None else _validated_delivery(body.deliver_to)),
    )
    if a is None:
        raise HTTPException(status_code=404, detail="Automation not found.")
    return _serialize(a)


@router.delete("/{automation_id}")
async def delete_(
    automation_id: str, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> dict[str, object]:
    user = _current_user(db, org_id, claims)
    _authorized_automation(db, org_id, automation_id, user)
    if not delete_automation(db, org_id, automation_id):
        raise HTTPException(status_code=404, detail="Automation not found.")
    return {"deleted": True}


@router.post(
    "/{automation_id}/run",
    dependencies=[Depends(rate_limit(*WORKFLOW_RUN_BUDGET))],
)
async def run_(
    automation_id: str, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> dict[str, object]:
    """Run an automation now through the shared runner (the Celery beat scheduler
    uses the same runner, so manual and scheduled runs behave identically)."""
    user = _current_user(db, org_id, claims)
    auto = _authorized_automation(db, org_id, automation_id, user)
    # The shared runner resolves the persisted creator; _authorized_automation
    # ensures the person pressing Run is that same user.
    return await execute_automation(db, auto)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/{automation_id}/token")
async def mint_trigger_token(
    automation_id: str, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> dict[str, object]:
    """Mint (or rotate) the external trigger token for one automation. The
    plaintext is returned exactly once; only its hash is stored."""
    user = _current_user(db, org_id, claims)
    auto = _authorized_automation(db, org_id, automation_id, user)
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
    automation_id: str, db: DbSession, org_id: WriteOrgId, claims: OptionalClaims
) -> dict[str, object]:
    user = _current_user(db, org_id, claims)
    auto = _authorized_automation(db, org_id, automation_id, user)
    auto.trigger_token_hash = None
    db.commit()
    return {"revoked": True}


# NOTE: no OrgId dependency — external callers authenticate with the scoped
# trigger token alone (PromptQL "Program API" equivalent). The token maps to
# exactly one automation in one org; a mismatch is a plain 401.
@trigger_router.post(
    "/{automation_id}/trigger",
    dependencies=[Depends(rate_limit(*PROVIDER_ACTION_BUDGET))],
    response_model=None,
)
async def trigger_automation(
    automation_id: str,
    request: Request,
    db: DbSession,
    x_trigger_token: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
    body: dict[str, object] | None = None,
) -> dict[str, object] | JSONResponse:
    """Run once per idempotency key.

    Completed/ambiguous results replay for seven days; after retention expiry,
    reusing the key is a new request. Repository cleanup removes at most 100
    expired rows per accepted call.
    """
    auto = db.get(Automation, automation_id)
    if (
        auto is None
        or not auto.trigger_token_hash
        or not x_trigger_token
        or not secrets.compare_digest(auto.trigger_token_hash, _hash_token(x_trigger_token))
    ):
        raise HTTPException(status_code=401, detail="Invalid trigger token.")
    assert_writable_org(auto.org_id)
    await enforce_rate_limit(
        request,
        max_calls=WORKFLOW_RUN_BUDGET[0],
        window_seconds=WORKFLOW_RUN_BUDGET[1],
        verified_tenant_id=auto.org_id,
    )
    if not auto.enabled or (auto.status or "active") == "paused":
        raise HTTPException(status_code=409, detail="Automation is paused.")
    key, request_hash = _validated_idempotency_request(idempotency_key, body)
    reservation, trigger_request = reserve_automation_trigger(
        db,
        automation_id=auto.id,
        org_id=auto.org_id,
        idempotency_key=key,
        request_hash=request_hash,
    )
    if reservation == "conflict":
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used with a different payload.",
        )
    if reservation == "replay":
        if trigger_request.status == "running":
            return JSONResponse(
                status_code=202,
                content={"request_id": trigger_request.id, "status": "accepted"},
                headers={"Idempotency-Replayed": "true"},
            )
        return JSONResponse(
            status_code=trigger_request.http_status or 502,
            content=trigger_request.response
            or {
                "request_id": trigger_request.id,
                "status": "outcome_unknown",
            },
            headers={"Idempotency-Replayed": "true"},
        )

    try:
        result = jsonable_encoder(await execute_automation(db, auto))
    except Exception:  # noqa: BLE001 - execution may already have external effects
        db.rollback()
        response = {
            "request_id": trigger_request.id,
            "status": "outcome_unknown",
            "detail": "Automation outcome is unknown; do not retry with a new key.",
        }
        try:
            finish_automation_trigger(
                db,
                request_id=trigger_request.id,
                status="outcome_unknown",
                response=response,
                http_status=502,
            )
        except Exception:  # noqa: BLE001 - running reservation still blocks duplicate work
            db.rollback()
        return JSONResponse(status_code=502, content=response)

    response = result if isinstance(result, dict) else {"result": result}
    response.setdefault("request_id", trigger_request.id)
    try:
        persisted = finish_automation_trigger(
            db,
            request_id=trigger_request.id,
            status="completed",
            response=response,
            http_status=200,
        )
    except Exception:  # noqa: BLE001 - running reservation remains fail-closed
        db.rollback()
        persisted = False
    if not persisted:
        raise HTTPException(
            status_code=503,
            detail="Automation ran, but its idempotency result could not be recorded.",
        )
    return response
