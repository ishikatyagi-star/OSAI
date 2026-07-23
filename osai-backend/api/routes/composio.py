"""Composio integration endpoints - catalog, OAuth connection, and sync."""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.ratelimit import (
    INGEST_START_BUDGET,
    OAUTH_START_BUDGET,
    PROVIDER_ACTION_BUDGET,
    enforce_rate_limit,
    rate_limit,
)
from config import settings
from connectors.composio_ingest import (
    SUPPORTED_INGESTION_TOOLKITS,
    ingest_composio_toolkit,
    purge_connector_data,
    sync_all_connections,
)
from connectors.composio_tool import composio_identity, get_default_composio_client
from db.models import OAuthStateUse, User
from db.session import (
    SessionLocal,
    assert_writable_org,
    get_db,
    get_org_id,
    require_admin,
    require_writable_org,
)

router = APIRouter(prefix="/integrations/composio", tags=["composio"])
OrgId = Annotated[str, Depends(get_org_id)]
WriteOrgId = Annotated[str, Depends(require_writable_org)]
DbSession = Annotated[Session, Depends(get_db)]
# Connecting, disconnecting, and syncing apps change org-wide connector state and
# spend embedding budget - admin-only, which also keeps the anonymous demo
# workspace read-only (SEC-003, SEC-008).
AdminOnly = Annotated[dict, Depends(require_admin)]

_OAUTH_STATE_AUDIENCE = "osai-composio-callback"
_OAUTH_STATE_ISSUER = "osai"
_OAUTH_STATE_PURPOSE = "composio-connect"
_OAUTH_STATE_TTL_SECONDS = 10 * 60


def _client_or_404():
    client = get_default_composio_client()
    if not client.available():
        raise HTTPException(status_code=404, detail="Composio is not configured")
    return client


def _issue_oauth_state(
    org_id: str,
    admin_id: str,
    toolkit: str,
    *,
    ttl_seconds: int = _OAUTH_STATE_TTL_SECONDS,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": _OAUTH_STATE_ISSUER,
            "aud": _OAUTH_STATE_AUDIENCE,
            "purpose": _OAUTH_STATE_PURPOSE,
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": secrets.token_urlsafe(18),
            "org_id": org_id,
            "admin_id": admin_id,
            "toolkit": toolkit,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def _decode_oauth_state(state: str) -> dict:
    if not state or len(state) > 4096:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")
    try:
        payload = jwt.decode(
            state,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=_OAUTH_STATE_AUDIENCE,
            issuer=_OAUTH_STATE_ISSUER,
            leeway=5,
            options={
                "require": [
                    "purpose",
                    "iat",
                    "exp",
                    "jti",
                    "org_id",
                    "admin_id",
                    "toolkit",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.") from exc
    if payload.get("purpose") != _OAUTH_STATE_PURPOSE or any(
        not isinstance(payload.get(key), str) or not payload[key]
        for key in ("jti", "org_id", "admin_id", "toolkit")
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")
    return payload


async def _limit_oauth_callback(
    request: Request,
    state: str | None = None,
    org_id: str | None = None,
) -> None:
    """Charge only valid signed callback state to its bound tenant."""
    if org_id is not None or not state:
        return
    try:
        payload = _decode_oauth_state(state)
    except HTTPException:
        return
    await enforce_rate_limit(
        request,
        max_calls=OAUTH_START_BUDGET[0],
        window_seconds=OAUTH_START_BUDGET[1],
        verified_tenant_id=payload["org_id"],
    )


_limit_oauth_callback.rate_limit_budget = OAUTH_START_BUDGET  # type: ignore[attr-defined]


def _mark_oauth_state_used(db: Session, payload: dict) -> None:
    """Atomically consume a state across workers and process restarts."""
    now = datetime.now(UTC)
    jti_hash = hashlib.sha256(payload["jti"].encode()).hexdigest()
    db.query(OAuthStateUse).filter(OAuthStateUse.expires_at < now).delete(synchronize_session=False)
    db.add(
        OAuthStateUse(
            jti_hash=jti_hash,
            expires_at=datetime.fromtimestamp(int(payload["exp"]), UTC),
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="OAuth state has already been used.") from exc


@router.get("/toolkits")
async def list_toolkits(
    search: str | None = None, cursor: str | None = None, limit: int = 50
) -> dict:
    """List only Composio apps whose content Sheldon can actually index."""
    _client_or_404()
    names = {"googledrive": "Google Drive"}
    needle = (search or "").casefold()
    items = [
        {
            "slug": slug,
            "name": names.get(slug, slug.title()),
            "no_auth": False,
            "tools_count": None,
            "logo": None,
            "categories": ["Content"],
        }
        for slug in sorted(SUPPORTED_INGESTION_TOOLKITS)
        if not needle
        or needle in slug.casefold()
        or needle in names.get(slug, slug.title()).casefold()
    ][: min(limit, 100)]
    return {"items": items, "next_cursor": None}


@router.get("/tools")
async def list_tools(toolkit: str | None = None) -> list[dict]:
    """Tools exposed by the configured (or a given) toolkit, in agent-spec form."""
    client = _client_or_404()
    toolkits = [toolkit] if toolkit else None
    return await client.list_tools(toolkits)


@router.post(
    "/connect/{toolkit}",
    dependencies=[Depends(rate_limit(*OAUTH_START_BUDGET))],
)
async def connect(toolkit: str, org_id: WriteOrgId, _admin: AdminOnly) -> dict:
    """Begin OAuth with a signed callback bound to org, admin, and toolkit."""
    admin_id = _admin.get("sub")
    if not admin_id or _admin.get("org_id") != org_id:
        raise HTTPException(status_code=403, detail="Current workspace admin required.")
    toolkit = toolkit.strip().lower()
    if not toolkit:
        raise HTTPException(status_code=422, detail="Toolkit is required.")
    if toolkit not in SUPPORTED_INGESTION_TOOLKITS:
        supported = ", ".join(sorted(SUPPORTED_INGESTION_TOOLKITS))
        raise HTTPException(
            status_code=422,
            detail=f"Sheldon cannot index {toolkit!r}. Supported toolkits: {supported}.",
        )

    callback_url = None
    if settings.public_base_url:
        state = _issue_oauth_state(org_id, admin_id, toolkit)
        callback_url = (
            f"{settings.public_base_url.rstrip('/')}"
            f"/integrations/composio/callback?{urlencode({'state': state})}"
        )
    # Scope the connection to the connecting user when per-user connections are
    # on, so each person links their own account; org-level otherwise.
    identity = composio_identity(org_id, admin_id)
    result = await _client_or_404().connect(toolkit, identity, callback_url=callback_url)
    # "needs_api_key" is an expected outcome (API-key app, no one-click flow), not
    # a server failure — return it as 200 so the UI can show the honest message
    # instead of a thrown generic error. Genuine failures still 400.
    if result.get("error") and result["error"] != "needs_api_key":
        raise HTTPException(status_code=400, detail=result["error"])
    return result


async def _sync_in_background(org_id: str, owner_user_id: str = "") -> None:
    """Run post-connect ingestion off the callback request path, scoped to the
    connecting user (per-user when enabled, else org-level)."""
    with SessionLocal() as db:
        try:
            await sync_all_connections(org_id, db, owner_user_id=owner_user_id)
        except Exception:  # noqa: BLE001 - background sync is best-effort
            pass


@router.get(
    "/callback",
    dependencies=[Depends(_limit_oauth_callback)],
)
async def callback(
    background_tasks: BackgroundTasks,
    db: DbSession,
    state: str | None = None,
    org_id: str | None = None,
) -> RedirectResponse:
    """Validate and consume OAuth state, then enqueue the bound org's ingest."""
    if org_id is not None or not state:
        raise HTTPException(
            status_code=400,
            detail="Signed OAuth state is required; raw org IDs are not accepted.",
        )
    payload = _decode_oauth_state(state)
    assert_writable_org(payload["org_id"])
    admin = db.get(User, payload["admin_id"])
    if admin is None or admin.org_id != payload["org_id"] or admin.role != "admin":
        raise HTTPException(status_code=403, detail="OAuth initiator is no longer an admin.")
    _mark_oauth_state_used(db, payload)

    client = get_default_composio_client()
    if client.available():
        # The OAuth state binds the connecting admin; ingest their connection
        # under their own ownership (per-user when enabled).
        background_tasks.add_task(
            _sync_in_background, payload["org_id"], payload["admin_id"]
        )
    base = settings.frontend_redirect.rstrip("/")
    return RedirectResponse(url=f"{base}/integrations?connected=1")


@router.post(
    "/sync",
    dependencies=[Depends(rate_limit(*INGEST_START_BUDGET))],
)
async def sync(org_id: WriteOrgId, db: DbSession, _admin: AdminOnly) -> dict:
    """Auto-detect the caller's connected apps and ingest them (idempotent)."""
    return await sync_all_connections(org_id, db, owner_user_id=_admin.get("sub", ""))


@router.get("/connections")
async def list_connections(org_id: OrgId) -> list[dict]:
    """Connected accounts for this org."""
    return await _client_or_404().list_connections(org_id)


@router.post(
    "/disconnect/{toolkit}",
    dependencies=[Depends(rate_limit(*PROVIDER_ACTION_BUDGET))],
)
async def disconnect(toolkit: str, org_id: WriteOrgId, db: DbSession, _admin: AdminOnly) -> dict:
    """Disconnect the toolkit and purge all data that account contributed."""
    # Revoke the caller's own connection under the same identity scheme used to
    # create it (per-user when enabled, else org-level).
    identity = composio_identity(org_id, _admin.get("sub"))
    result = await _client_or_404().disconnect(toolkit, identity)
    removed = await purge_connector_data(db, org_id, toolkit)
    db.commit()
    return {**result, "documents_removed": removed}


@router.post(
    "/{toolkit}/ingest",
    dependencies=[Depends(rate_limit(*INGEST_START_BUDGET))],
)
async def ingest(toolkit: str, org_id: WriteOrgId, db: DbSession, _admin: AdminOnly) -> dict:
    """Pull documents from a connected Composio toolkit into the org brain."""
    _client_or_404()
    result = await ingest_composio_toolkit(org_id, toolkit, db)
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result
