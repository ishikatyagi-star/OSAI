import asyncio
import logging
import re
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.ratelimit import INGEST_START_BUDGET, rate_limit
from connectors.composio_ingest import SUPPORTED_INGESTION_TOOLKITS, ingest_composio_toolkit
from connectors.composio_tool import composio_identity, get_default_composio_client
from connectors.toolkit_map import (
    HARD_DISABLED_CONNECTOR_KEYS,
    to_source_key,
    to_toolkit_slug,
)
from db.models import ConnectorAccount, SourceDocumentRecord, utc_iso
from db.repositories import list_integrations as list_db_integrations
from db.repositories import user_clearance, user_permissions
from db.session import (
    SessionLocal,
    get_db,
    get_optional_claims,
    get_org_id,
    require_admin,
    require_writable_org,
)
from memory.retriever import _tier_visible, _visible

router = APIRouter(prefix="/integrations", tags=["integrations"])
logger = logging.getLogger("osai.integrations")
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
WriteOrgId = Annotated[str, Depends(require_writable_org)]
AdminOnly = Annotated[dict, Depends(require_admin)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

_CONNECTOR_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


def _known_connector_key(db: Session, org_id: str, connector_key: str) -> bool:
    """Accept an upload key or a Composio source already known to this org."""
    if not _CONNECTOR_KEY_RE.fullmatch(connector_key):
        return False
    if connector_key in HARD_DISABLED_CONNECTOR_KEYS:
        return False
    if connector_key == "upload":
        return True
    if db.scalar(
        select(ConnectorAccount.id).where(
            ConnectorAccount.org_id == org_id,
            ConnectorAccount.connector_key == connector_key,
        )
    ):
        return True
    return (
        db.scalar(
            select(SourceDocumentRecord.id)
            .where(
                SourceDocumentRecord.org_id == org_id,
                SourceDocumentRecord.source_type == connector_key,
            )
            .limit(1)
        )
        is not None
    )


@router.get("")
async def list_integrations(
    db: DbSession, org_id: OrgId, claims: OptionalClaims = None
) -> list[dict[str, object]]:
    """Return only connections that currently exist in Composio.

    Persisted rows provide sync metadata but are never treated as an independent
    connector or authentication source.
    """
    try:
        persisted = list_db_integrations(db, org_id)
    except SQLAlchemyError as exc:
        logger.exception("Could not list integrations (org=%s)", org_id)
        raise HTTPException(
            status_code=503,
            detail="Integrations are temporarily unavailable.",
        ) from exc

    client = get_default_composio_client()
    if not client.available():
        return []
    try:
        identity = composio_identity(org_id, (claims or {}).get("sub"))
        connections = await asyncio.wait_for(client.list_connections(identity), timeout=4)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not list Composio connections (org=%s)", org_id)
        raise HTTPException(
            status_code=503,
            detail="Composio connections are temporarily unavailable.",
        ) from exc

    persisted_by_key = {
        str(item["key"]): item
        for item in persisted
        if item.get("key") not in HARD_DISABLED_CONNECTOR_KEYS
    }
    live: dict[str, dict] = {}
    for connection in connections:
        toolkit = connection.get("toolkit")
        if not toolkit:
            continue
        key = to_source_key(toolkit)
        if key in HARD_DISABLED_CONNECTOR_KEYS:
            continue
        previous = live.get(key)
        status = (connection.get("status") or "").upper()
        previous_status = (previous.get("status") or "").upper() if previous else ""
        if previous is None or (status == "ACTIVE" and previous_status != "ACTIVE"):
            live[key] = connection

    items: list[dict[str, object]] = []
    for key, connection in live.items():
        toolkit = str(connection.get("toolkit") or key)
        item = dict(persisted_by_key.get(key, {}))
        item.update(
            {
                "key": key,
                "display_name": item.get("display_name")
                or toolkit.replace("_", " ").title(),
                "capabilities": (
                    ["sync", "search"]
                    if toolkit in SUPPORTED_INGESTION_TOOLKITS
                    else ["execute"]
                ),
                "auth_state": (
                    "connected"
                    if (connection.get("status") or "").upper() == "ACTIVE"
                    else "expired"
                ),
                "scopes": item.get("scopes") or [],
                "last_sync": item.get("last_sync"),
                "sync_error": item.get("sync_error"),
                "account_email": connection.get("email") or item.get("account_email"),
                "source": "composio",
            }
        )
        items.append(item)
    return items


@router.get("/{connector_key}/documents")
async def list_connector_documents(
    connector_key: str,
    db: DbSession,
    org_id: OrgId,
    claims: OptionalClaims,
    limit: Annotated[int, Query(ge=1, le=500)] = 25,
) -> list[dict[str, object]]:
    """Recently indexed documents for a connector."""
    if not _known_connector_key(db, org_id, connector_key):
        raise HTTPException(status_code=404, detail="Unknown connector")
    requester_permissions = user_permissions(db, claims)
    requester_tier = user_clearance(db, claims)
    statement = (
        select(SourceDocumentRecord)
        .where(
            SourceDocumentRecord.org_id == org_id,
            SourceDocumentRecord.source_type == connector_key,
        )
        .order_by(desc(SourceDocumentRecord.ingested_at))
        .execution_options(yield_per=min(max(limit, 25), 100))
    )
    rows: list[SourceDocumentRecord] = []
    for row in db.scalars(statement):
        if _visible(row.permissions, requester_permissions) and _tier_visible(
            row.data_tier, requester_tier
        ):
            rows.append(row)
            if len(rows) == limit:
                break
    return [
        {
            "id": document.id,
            "title": document.title or "Untitled",
            "url": document.url,
            "data_tier": document.data_tier,
            "updated_at": utc_iso(
                document.source_updated_at or document.ingested_at
            ),
        }
        for document in rows
    ]


_INFLIGHT_INGESTS: set[tuple[str, str, str]] = set()


async def _ingest_composio_in_background(org_id: str, slug: str, owner_user_id: str = "") -> None:
    """Run a Composio re-ingest off the request path, with its own DB session.

    A full re-sync (25 files + media transcription + embeddings) easily exceeds
    the client's request timeout; run inline it left the UI stuck on "Syncing…"
    and the request was cancelled before ingest_composio_toolkit could record a
    sync run — so /sync-runs showed nothing. As a background task it always runs
    to completion and records its result. Scoped to the connection owner.
    """
    key = (org_id, owner_user_id, slug)
    if key in _INFLIGHT_INGESTS:
        return
    _INFLIGHT_INGESTS.add(key)
    try:
        with SessionLocal() as db:
            try:
                # ingest_composio_toolkit always records a sync run (success or a
                # visible failed run), so a swallowed error here can't leave
                # /sync-runs empty.
                await ingest_composio_toolkit(org_id, slug, db, owner_user_id=owner_user_id)
            except Exception:  # noqa: BLE001 — never crash the background worker
                logger.exception("Composio ingest failed (org=%s, toolkit=%s)", org_id, slug)
    finally:
        _INFLIGHT_INGESTS.discard(key)


@router.post(
    "/{connector_key}/sync",
    dependencies=[Depends(rate_limit(*INGEST_START_BUDGET))],
)
async def trigger_sync(
    connector_key: str,
    db: DbSession,
    org_id: WriteOrgId,
    background_tasks: BackgroundTasks,
    _admin: AdminOnly,
) -> dict[str, object]:
    del db
    if connector_key in HARD_DISABLED_CONNECTOR_KEYS:
        raise HTTPException(status_code=404, detail="Unknown connector")
    client = get_default_composio_client()
    if not client.available():
        raise HTTPException(status_code=503, detail="Composio is not configured")
    slug = to_toolkit_slug(connector_key)
    owner_user_id = _admin.get("sub", "")
    identity = composio_identity(org_id, owner_user_id)
    connections = await client.list_connections(identity)
    statuses = {
        (connection.get("status") or "").upper()
        for connection in connections
        if connection.get("toolkit") == slug
    }
    if "ACTIVE" in statuses:
        background_tasks.add_task(
            _ingest_composio_in_background, org_id, slug, owner_user_id
        )
        return {
            "connector_key": connector_key,
            "status": "started",
            "documents_indexed": 0,
        }
    if statuses:
        return {
            "connector_key": connector_key,
            "status": "reconnect_required",
            "documents_indexed": 0,
            "message": "This connection has expired. Reconnect the app to resume syncing.",
        }
    raise HTTPException(status_code=404, detail="Unknown connector")


@router.get("/{connector_key}/healthcheck")
async def connector_healthcheck(
    connector_key: str, org_id: OrgId, claims: OptionalClaims
) -> dict[str, object]:
    if connector_key in HARD_DISABLED_CONNECTOR_KEYS:
        raise HTTPException(status_code=404, detail="Unknown connector")
    client = get_default_composio_client()
    if not client.available():
        raise HTTPException(status_code=503, detail="Composio is not configured")
    slug = to_toolkit_slug(connector_key)
    identity = composio_identity(org_id, (claims or {}).get("sub"))
    connections = await client.list_connections(identity)
    matching = [connection for connection in connections if connection.get("toolkit") == slug]
    if not matching:
        raise HTTPException(status_code=404, detail="Unknown connector")
    healthy = any(
        (connection.get("status") or "").upper() == "ACTIVE"
        for connection in matching
    )
    return {
        "connector_key": connector_key,
        "healthy": healthy,
        "message": (
            "Connected via Composio."
            if healthy
            else "The Composio connection needs to be reconnected."
        ),
    }
