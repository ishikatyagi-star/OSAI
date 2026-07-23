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
from connectors.registry import HARD_DISABLED_CONNECTOR_KEYS, connector_registry
from connectors.sync_service import sync_connector
from connectors.toolkit_map import NATIVE_TO_COMPOSIO, to_native_key
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
# Writes must never come from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
AdminOnly = Annotated[dict, Depends(require_admin)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

_CONNECTOR_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


def _known_connector_key(db: Session, org_id: str, connector_key: str) -> bool:
    """Accept a normalized native/upload key or a connector configured for this org."""
    if not _CONNECTOR_KEY_RE.fullmatch(connector_key):
        return False
    if connector_key in HARD_DISABLED_CONNECTOR_KEYS:
        return False
    if connector_key == "upload" or connector_key in {
        connector.key for connector in connector_registry.all()
    }:
        return True
    if db.scalar(
        select(ConnectorAccount.id).where(
            ConnectorAccount.org_id == org_id,
            ConnectorAccount.connector_key == connector_key,
        )
    ):
        return True
    # Preserve legacy/dynamic Composio sources that predate ConnectorAccount
    # persistence, while still rejecting arbitrary caller-chosen source keys.
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
    # Only integrations the org has actually configured. A fresh workspace gets
    # an empty list — the frontend renders its empty state pointing at the full
    # Composio catalog instead of a fixed set of native connector cards.
    try:
        items = list_db_integrations(db, org_id)
    except SQLAlchemyError as exc:
        logger.exception("Could not list integrations (org=%s)", org_id)
        raise HTTPException(
            status_code=503,
            detail="Integrations are temporarily unavailable.",
        ) from exc
    items = [
        it
        for it in items
        if it.get("auth_state") != "not_configured"
        and it.get("key") not in HARD_DISABLED_CONNECTOR_KEYS
    ]
    for item in items:
        item["source"] = "native"

    # Overlay live Composio connections onto the matching native card so an
    # authorized app reads "connected" even if ingestion hasn't run yet. The
    # Composio slug maps to one native key, keeping it a single card.
    client = get_default_composio_client()
    if client.available():
        try:
            # Bounded well under the frontend's fetch budget: if Composio is
            # slow the page must still render from the DB (overlay is optional),
            # not time out client-side and show a load error.
            # Show the caller's own connections (per-user when enabled), so the
            # Integrations page reflects what this person has connected, not a
            # shared org pool.
            identity = composio_identity(org_id, (claims or {}).get("sub"))
            connections = await asyncio.wait_for(client.list_connections(identity), timeout=4)
            # Collapse to one connection per native key, preferring ACTIVE. A key
            # whose only connection is EXPIRED must read "expired" (needs
            # reconnect), never "connected" — otherwise the card looks healthy
            # while every sync 404s. Google expires OAuth tokens for apps in
            # "Testing" publishing status after ~7 days, so this is the common
            # steady state, not an edge case.
            live: dict[str, dict] = {}
            for c in connections:
                tk = c.get("toolkit")
                if not tk:
                    continue
                key = to_native_key(tk)
                if key in HARD_DISABLED_CONNECTOR_KEYS:
                    continue
                status = (c.get("status") or "").upper()
                prev = live.get(key)
                prev_status = (prev.get("status") or "").upper() if prev else ""
                # ACTIVE always wins; otherwise keep the first seen.
                if prev is None or (status == "ACTIVE" and prev_status != "ACTIVE"):
                    live[key] = c
            by_key = {it["key"]: it for it in items}
            native_keys = {connector.key for connector in connector_registry.all()}
            for key, conn in live.items():
                status = (conn.get("status") or "").upper()
                auth_state = "connected" if status == "ACTIVE" else "expired"
                toolkit = conn.get("toolkit") or key
                if key in by_key:
                    by_key[key]["auth_state"] = auth_state
                    by_key[key]["source"] = "composio"
                    if key not in native_keys:
                        by_key[key]["capabilities"] = (
                            ["sync", "search"]
                            if toolkit in SUPPORTED_INGESTION_TOOLKITS
                            else ["execute"]
                        )
                    # Prefer the live account email if we have it (may be fresher
                    # than what the last sync persisted).
                    if conn.get("email") and not by_key[key].get("account_email"):
                        by_key[key]["account_email"] = conn.get("email")
                elif status == "ACTIVE" or key not in {it["key"] for it in items}:
                    # A catalog connector with no native counterpart (e.g. Gmail,
                    # Linear via Composio) — synthesize a card so anything the
                    # user connects from the full catalog is visible here,
                    # including an expired one so they can reconnect it.
                    items.append(
                        {
                            "key": key,
                            "display_name": toolkit.replace("_", " ").title(),
                            "capabilities": (
                                ["sync", "search"]
                                if toolkit in SUPPORTED_INGESTION_TOOLKITS
                                else ["execute"]
                            ),
                            "auth_state": auth_state,
                            "scopes": [],
                            "last_sync": None,
                            "sync_error": None,
                            "account_email": conn.get("email"),
                            "source": "composio",
                        }
                    )
        except Exception:  # noqa: BLE001 — connection overlay is best-effort
            pass

    return items


@router.get("/{connector_key}/documents")
async def list_connector_documents(
    connector_key: str,
    db: DbSession,
    org_id: OrgId,
    claims: OptionalClaims,
    limit: Annotated[int, Query(ge=1, le=500)] = 25,
) -> list[dict[str, object]]:
    """Recently indexed documents for a connector, so the UI can show what synced."""
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
            "id": d.id,
            "title": d.title or "Untitled",
            "url": d.url,
            "data_tier": d.data_tier,
            "updated_at": (
                utc_iso(d.source_updated_at) if d.source_updated_at else utc_iso(d.ingested_at)
            ),
        }
        for d in rows
    ]


# One ingest per (org, toolkit) at a time. Double-clicking "Sync Now" (or a UI
# retry) used to stack two full ingests in the same process, doubling memory
# pressure on the tiny prod instance — the second click should be a no-op.
_INFLIGHT_INGESTS: set[tuple[str, str]] = set()


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
                pass
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
    if connector_key in HARD_DISABLED_CONNECTOR_KEYS:
        raise HTTPException(status_code=404, detail="Unknown connector")
    # Catalog apps (e.g. Gmail) have no native connector, so an unknown key is
    # only an error when there's also no active Composio connection for it.
    is_native = connector_key in {connector.key for connector in connector_registry.all()}

    # If this app is connected through Composio OAuth, ingest via Composio (no
    # native service-account credentials needed, e.g. Google Drive). Only fall
    # back to the native connector when there's no active Composio connection.
    client = get_default_composio_client()
    if client.available():
        slug = NATIVE_TO_COMPOSIO.get(connector_key, connector_key)
        owner_user_id = _admin.get("sub", "")
        statuses: set[str] = set()
        try:
            # Scope to the caller's own connection (per-user when enabled).
            identity = composio_identity(org_id, owner_user_id)
            connections = await client.list_connections(identity)
            statuses = {
                (c.get("status") or "").upper()
                for c in connections
                if c.get("toolkit") == slug
            }
        except Exception:  # noqa: BLE001 — fall back to native sync on lookup failure
            statuses = set()
        if "ACTIVE" in statuses:
            # Kick the ingest off in the background and return immediately so the
            # UI can show "sync started" and poll /sync-runs for the result.
            background_tasks.add_task(
                _ingest_composio_in_background, org_id, slug, owner_user_id
            )
            return {
                "connector_key": connector_key,
                "status": "started",
                "documents_indexed": 0,
            }
        if statuses and not is_native:
            # The connection exists but isn't usable (expired/initiated). Tell the
            # user to reconnect instead of failing with an opaque error — this is
            # the common "worked yesterday, 404s today" case for OAuth tokens that
            # expire (e.g. Google Testing-mode refresh tokens after ~7 days).
            return {
                "connector_key": connector_key,
                "status": "reconnect_required",
                "documents_indexed": 0,
                "message": "This connection has expired. Reconnect the app to resume syncing.",
            }

    if not is_native:
        raise HTTPException(status_code=404, detail="Unknown connector")
    return await sync_connector(connector_key, org_id, db)


@router.get("/{connector_key}/healthcheck")
async def connector_healthcheck(connector_key: str, org_id: OrgId) -> dict[str, object]:
    if connector_key in HARD_DISABLED_CONNECTOR_KEYS:
        raise HTTPException(status_code=404, detail="Unknown connector")
    # Catalog apps have no native connector; only 404 when Composio has no
    # active connection for the key either (checked below).
    is_native = connector_key in {connector.key for connector in connector_registry.all()}

    # If the app is connected via Composio OAuth, report on that connection rather
    # than the native connector (which would ask for service-account creds).
    client = get_default_composio_client()
    if client.available():
        slug = NATIVE_TO_COMPOSIO.get(connector_key, connector_key)
        try:
            connections = await client.list_connections(org_id)
            if any(
                c.get("toolkit") == slug and (c.get("status") or "").upper() == "ACTIVE"
                for c in connections
            ):
                return {
                    "connector_key": connector_key,
                    "healthy": True,
                    "message": "Connected via Composio (OAuth).",
                }
        except Exception:  # noqa: BLE001 — fall back to native healthcheck
            pass

    if not is_native:
        raise HTTPException(status_code=404, detail="Unknown connector")
    connector = connector_registry.get(connector_key)
    result = await connector.healthcheck(org_id)
    return {
        "connector_key": result.connector_key,
        "healthy": result.healthy,
        "message": result.message,
    }
