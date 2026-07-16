"""Ingest a user's documents from a Composio-connected app into OSAI's brain.

Flow: user connects an app via OAuth (POST /integrations/composio/connect/{tk}),
then this pulls their content through Composio's tools and indexes it into the
same RAG pipeline the native connectors use (Postgres source_documents + chunks
+ Qdrant vectors). No token-sharing — auth lives in the Composio connection.

Notion is implemented first; add other toolkits by extending `_FETCHERS`.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from api.schemas.connector import SourceDocument
from config import settings
from connectors.composio_tool import ComposioClient, get_default_composio_client
from connectors.toolkit_map import to_native_key
from db.models import now_utc
from db.repositories import (
    apply_tier_rules,
    chunks_for_documents,
    ensure_connector_account,
    purge_source_type,
    record_sync_result,
    upsert_source_documents,
)
from memory.qdrant_store import QdrantStore, get_default_qdrant_store

logger = logging.getLogger("osai.composio.ingest")

# Audio/video files Whisper can transcribe (≤25MB per the API limit).
_MEDIA_EXTS = (".mp3", ".mp4", ".m4a", ".wav", ".webm", ".mpeg", ".mpga", ".ogg", ".mov")
_WHISPER_MAX_BYTES = 25 * 1024 * 1024

# Never download file content bigger than this: the Composio download tool
# inlines the whole file (base64) in its JSON response, which execute() buffers
# fully in RAM — several copies of a big file at once OOM-kills the 512MB prod
# instance. Oversized files are indexed by name with skipped_large_file=True.
_MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024


def _file_size(f: dict) -> int | None:
    """Size in bytes from a Drive listing entry (str or int; absent for
    Google-native docs, which export small)."""
    for key in ("size", "sizeBytes", "size_bytes", "quotaBytesUsed"):
        v = f.get(key)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return None


def _is_media(name: str) -> bool:
    return name.lower().endswith(_MEDIA_EXTS)


def _find_url(data: Any) -> str | None:
    """Best-effort: find the first http(s) URL anywhere in a Composio response."""
    if isinstance(data, str):
        return data if data.startswith("http") else None
    if isinstance(data, dict):
        for v in data.values():
            if (u := _find_url(v)) :
                return u
    if isinstance(data, list):
        for v in data:
            if (u := _find_url(v)) :
                return u
    return None


async def _transcribe_media(client: ComposioClient, fid: str, name: str, org_id: str) -> str | None:
    """Download a Drive media file via Composio and transcribe it with Whisper
    (Groq by default; OpenAI-compatible). Best-effort: returns None (caller falls
    back to the filename) if no transcription key, the file is too big, or the
    bytes can't be retrieved."""
    if not settings.transcribe_key:
        return None
    try:
        # Capped so the buffered response can never exceed what Whisper accepts
        # anyway (base64 inflates ~4/3x) — execute() would buffer it unbounded.
        dl = await client.execute_capped(
            "GOOGLEDRIVE_DOWNLOAD_FILE",
            {"file_id": fid},
            org_id,
            max_bytes=_WHISPER_MAX_BYTES * 2,
        )
    except Exception:  # noqa: BLE001
        return None
    data = dl.get("data") or {}

    audio: bytes | None = None
    for key in ("content", "file_content", "base64"):
        v = _dig(data, key) or _dig(data, "response_data", key)
        if isinstance(v, str) and len(v) > 100:
            # base64 inflates ~4/3×; reject before decoding so we never
            # materialise an oversized file in memory (free-tier RAM is tight).
            if len(v) > _WHISPER_MAX_BYTES * 4 // 3 + 4:
                return None
            try:
                # Decode off the event loop: a ~33MB base64 decode on the tiny
                # prod CPU (0.15 vCPU) stalls the loop long enough for Render's
                # 5s /health probe to fail and kill the instance mid-sync.
                audio = await asyncio.to_thread(base64.b64decode, v)
                break
            except Exception:  # noqa: BLE001
                pass
    if audio is None and (url := _find_url(data)):
        try:
            async with httpx.AsyncClient(timeout=60) as h:
                async with h.stream("GET", url) as r:
                    if r.status_code != 200:
                        return None
                    # Stream with a hard cap: abort as soon as the download
                    # exceeds the Whisper limit rather than buffering it all.
                    buf = bytearray()
                    async for chunk in r.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > _WHISPER_MAX_BYTES:
                            return None
                    audio = bytes(buf)
        except Exception:  # noqa: BLE001
            return None

    if not audio or len(audio) > _WHISPER_MAX_BYTES:
        return None

    try:
        async with httpx.AsyncClient(timeout=180) as h:
            resp = await h.post(
                f"{settings.transcribe_base_url.rstrip('/')}/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.transcribe_key}"},
                files={"file": (name, audio)},
                data={"model": settings.transcribe_model, "response_format": "json"},
            )
        if resp.status_code == 200:
            return resp.json().get("text") or None
        logger.warning("Whisper transcription %s -> %s", name, resp.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Whisper transcription error for %s: %s", name, exc)
    return None


async def _handle_account_change(
    session: Session,
    client: ComposioClient,
    org_id: str,
    toolkit: str,
    native_key: str,
    qdrant_store: QdrantStore,
) -> None:
    """Detect a reconnect with a different external account and purge the old
    account's indexed data. Records the account identity (id + email) on the
    ConnectorAccount so the UI can show who's connected and what changed."""
    try:
        identity = await client.connection_identity(toolkit, org_id)
    except Exception:  # noqa: BLE001 — identity is best-effort; never block sync
        identity = None
    if not identity or not identity.get("id"):
        return

    account = ensure_connector_account(session, org_id, native_key)
    config = dict(account.config or {})
    prev_id = config.get("account_external_id")
    new_id = identity["id"]

    if prev_id and prev_id != new_id:
        # Different account than last sync — remove the previous account's docs
        # from Postgres and Qdrant so they can't be counted or retrieved.
        purge_source_type(session, org_id, native_key)
        try:
            await qdrant_store.delete_source_type(org_id, native_key)
        except Exception:  # noqa: BLE001 — vector cleanup is best-effort
            logger.warning("Qdrant purge failed for %s/%s", org_id, native_key)
        config["previous_account_email"] = config.get("account_email")
        config["last_reconnected_at"] = now_utc().isoformat()

    config["account_external_id"] = new_id
    config["account_email"] = identity.get("email")
    account.config = config
    account.auth_state = "connected"
    session.flush()


async def purge_connector_data(
    session: Session,
    org_id: str,
    toolkit: str,
    *,
    qdrant_store: QdrantStore | None = None,
) -> int:
    """Remove every document a connector ingested into this org, from Postgres
    (source_documents + chunks) and Qdrant (vectors), and mark the account
    disconnected with its identity cleared.

    Called on disconnect so a Google (or any) account that is no longer in sync
    leaves nothing behind: switching the connected account = disconnect (this
    purge) then connect + sync the new account, which cannot then mix the two.
    Returns the number of source documents removed."""
    qdrant_store = qdrant_store or get_default_qdrant_store()
    native_key = to_native_key(toolkit)

    removed = purge_source_type(session, org_id, native_key)
    try:
        await qdrant_store.delete_source_type(org_id, native_key)
    except Exception:  # noqa: BLE001 — vector cleanup is best-effort
        logger.warning("Qdrant purge failed on disconnect for %s/%s", org_id, native_key)

    # Reset the account so a later reconnect starts clean (no stale identity that
    # would make the reconnect path think the account is unchanged).
    account = ensure_connector_account(session, org_id, native_key)
    config = dict(account.config or {})
    for k in ("account_external_id", "account_email", "previous_account_email"):
        config.pop(k, None)
    account.config = config
    account.auth_state = "disconnected"
    account.last_sync_at = None
    session.flush()
    return removed


async def ingest_composio_toolkit(
    org_id: str,
    toolkit: str,
    session: Session,
    *,
    client: ComposioClient | None = None,
    qdrant_store: QdrantStore | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    client = client or get_default_composio_client()
    qdrant_store = qdrant_store or get_default_qdrant_store()
    if not client.available():
        return {"status": "failed", "error": "Composio not configured", "documents_indexed": 0}

    fetcher = _FETCHERS.get(toolkit)
    if fetcher is None:
        return {
            "status": "failed",
            "error": f"Ingestion not implemented for toolkit {toolkit!r}",
            "documents_indexed": 0,
        }

    # Reconnect handling: if the org reconnected this toolkit with a *different*
    # external account, purge the previous account's documents so counts and Ask
    # reflect only the currently-connected account (never a mix of both).
    native_key = to_native_key(toolkit)
    await _handle_account_change(session, client, org_id, toolkit, native_key, qdrant_store)

    try:
        documents = await fetcher(client, org_id, limit)
    except Exception as exc:  # noqa: BLE001
        logger.error("Composio ingest %s failed: %s", toolkit, exc)
        return {"status": "failed", "error": str(exc), "documents_indexed": 0}

    if documents:
        # Same per-info sensitivity overrides the native connector sync path
        # applies (see connectors/sync_service.py) — tier rules are keyed by
        # the native connector key, so a Composio-ingested doc is classified
        # the same way a natively-synced one would be, instead of always
        # landing at the connector's default tier.
        apply_tier_rules(session, org_id, native_key, documents)
    indexed = upsert_source_documents(session, documents)
    vector_error = None
    # Embed and upsert one document at a time, yielding between documents.
    # Doing all ~25 documents' chunks in a single batch holds every embedding
    # in memory at once and hogs the tiny prod CPU (0.15 vCPU / 512MB) long
    # enough for Render's 5s /health probe to fail and kill the instance
    # mid-sync — a partial index that finishes beats a full one that dies.
    for document in documents:
        await asyncio.sleep(0)
        try:
            await qdrant_store.upsert_chunks(chunks_for_documents([document]))
        except Exception as exc:  # noqa: BLE001 — vectors shouldn't block source sync
            vector_error = str(exc)

    record_sync_result(
        session,
        org_id=org_id,
        # Attribute to the native connector key so the single Integrations card
        # reflects the connection/sync (Composio `googledrive` -> `google_drive`).
        connector_key=to_native_key(toolkit),
        status="succeeded" if documents else "partial",
        documents_seen=len(documents),
        documents_indexed=indexed,
        error=vector_error,
    )
    return {
        "status": "succeeded",
        "toolkit": toolkit,
        "documents_seen": len(documents),
        "documents_indexed": indexed,
        "vector_error": vector_error,
    }


# ---------------------------------------------------------------------------
# Toolkit-specific fetchers — turn a connected app's content into SourceDocuments
# ---------------------------------------------------------------------------


def _dig(data: Any, *keys: str) -> Any:
    """Walk nested dicts; Composio wraps API responses under data/response_data."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
    return data


def _first_list(*candidates: Any) -> list:
    for c in candidates:
        if isinstance(c, list):
            return c
    return []


async def _fetch_notion(client: ComposioClient, org_id: str, limit: int) -> list[SourceDocument]:
    # 1. List pages (empty query returns everything the connection can see).
    res = await client.execute("NOTION_SEARCH_NOTION_PAGE", {"query": ""}, org_id)
    data = res.get("data") or {}
    results = _first_list(
        _dig(data, "response_data", "results"),
        _dig(data, "results"),
        data if isinstance(data, list) else None,
    )

    documents: list[SourceDocument] = []
    for page in results[:limit]:
        await asyncio.sleep(0)  # keep /health responsive during ingest
        page_id = page.get("id")
        if not page_id:
            continue
        title = _notion_title(page) or "Untitled"
        url = page.get("url")
        # 2. Pull the page's text content.
        try:
            content = await client.execute(
                "NOTION_FETCH_BLOCK_CONTENTS", {"block_id": page_id}, org_id
            )
            text = _notion_blocks_text(content.get("data") or {})
        except Exception:  # noqa: BLE001
            text = ""
        documents.append(
            SourceDocument(
                source_id=f"notion:{page_id}",
                source_type="notion",
                org_id=org_id,
                external_id=page_id,
                title=title,
                url=url,
                text=text or title,
                permissions=["source:all"],
            )
        )
    return documents


def _notion_title(page: dict) -> str:
    props = page.get("properties") or {}
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    return ""


def _notion_blocks_text(data: dict) -> str:
    blocks = _first_list(_dig(data, "response_data", "results"), _dig(data, "results"))
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        payload = block.get(btype) if btype else None
        if isinstance(payload, dict):
            rich = payload.get("rich_text") or payload.get("text") or []
            parts.append("".join(t.get("plain_text", "") for t in rich if isinstance(t, dict)))
    return "\n".join(p for p in parts if p)


async def _text_from_download_url(data: Any) -> str:
    """Composio delivers exported file content as a temporary URL (R2), not
    inline — fetch it with a hard size cap. Only called for text exports."""
    url = _find_url(data)
    if not url:
        return ""
    try:
        async with httpx.AsyncClient(timeout=60) as h:
            async with h.stream("GET", url) as r:
                if r.status_code != 200:
                    return ""
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > _MAX_DOWNLOAD_BYTES:
                        return ""
        return bytes(buf).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — content extraction is best-effort
        return ""


async def _fetch_googledrive(
    client: ComposioClient, org_id: str, limit: int
) -> list[SourceDocument]:
    res = await client.execute("GOOGLEDRIVE_LIST_FILES", {"page_size": limit}, org_id)
    data = res.get("data") or {}
    files = _first_list(_dig(data, "response_data", "files"), _dig(data, "files"))

    documents: list[SourceDocument] = []
    for f in files[:limit]:
        # Yield between files so /health keeps answering while a sync hogs the
        # tiny prod CPU — otherwise Render kills the instance mid-ingest.
        await asyncio.sleep(0)
        fid = f.get("id")
        if not fid:
            continue
        name = f.get("name") or "Untitled"
        mime = f.get("mimeType") or f.get("mime_type") or ""
        if mime == "application/vnd.google-apps.folder":
            continue  # folders have no content; indexing them as docs is noise
        url = f.get("webViewLink") or f.get("web_view_link")
        text = ""
        metadata: dict[str, Any] = {}
        # GOOGLEDRIVE_DOWNLOAD_FILE returns the whole file base64-inlined in
        # JSON, and execute() buffers the full response — one big Drive file
        # materialises several times its size in RAM and OOM-kills the 512MB
        # prod instance (observed: instance died ~1 min into every real sync).
        # The listing gives us the size up front, so skip content for large
        # files and index them by name.
        size = _file_size(f)
        if size is not None and size > _MAX_DOWNLOAD_BYTES:
            documents.append(
                SourceDocument(
                    source_id=f"gdrive:{fid}",
                    source_type="google_drive",
                    org_id=org_id,
                    external_id=fid,
                    title=name,
                    url=url,
                    text=name,
                    metadata={"skipped_large_file": True, "size_bytes": size},
                    permissions=["source:all"],
                )
            )
            continue
        if _is_media(name):
            # Audio/video: transcribe with Whisper so the *content* is searchable,
            # not just the filename.
            transcript = await _transcribe_media(client, fid, name, org_id)
            if transcript:
                text = transcript
                metadata = {"media": True, "transcribed": True}
            else:
                metadata = {"media": True, "transcribed": False}
        else:
            args: dict[str, Any] = {"file_id": fid}
            is_workspace_doc = mime.startswith("application/vnd.google-apps")
            if is_workspace_doc:
                # Workspace files (Docs/Sheets/Slides) can't be downloaded
                # raw — the tool errors "mime_type is required for exporting
                # Google Workspace files" and the doc used to be indexed as
                # just its filename. Export to text.
                args["mime_type"] = (
                    "text/csv"
                    if mime == "application/vnd.google-apps.spreadsheet"
                    else "text/plain"
                )
            try:
                # Capped: Drive listings report no size, so the size check
                # above can't protect this call by itself.
                content = await client.execute_capped(
                    "GOOGLEDRIVE_DOWNLOAD_FILE",
                    args,
                    org_id,
                    max_bytes=_MAX_DOWNLOAD_BYTES * 2,
                )
                data = content.get("data") or {}
                text = _plain_text(data)
                if not text and is_workspace_doc:
                    # Exported content arrives as a temporary URL, not inline.
                    text = await _text_from_download_url(data)
            except Exception:  # noqa: BLE001
                text = ""
        documents.append(
            SourceDocument(
                source_id=f"gdrive:{fid}",
                source_type="google_drive",
                org_id=org_id,
                external_id=fid,
                title=name,
                url=url,
                text=text or name,
                metadata=metadata,
                permissions=["source:all"],
            )
        )
    return documents


async def _fetch_slack(client: ComposioClient, org_id: str, limit: int) -> list[SourceDocument]:
    res = await client.execute("SLACK_LIST_ALL_CHANNELS", {"limit": 20}, org_id)
    data = res.get("data") or {}
    channels = _first_list(
        _dig(data, "response_data", "channels"), _dig(data, "channels")
    )

    documents: list[SourceDocument] = []
    for ch in channels[:limit]:
        await asyncio.sleep(0)  # keep /health responsive during ingest
        cid = ch.get("id")
        if not cid:
            continue
        name = ch.get("name") or cid
        try:
            hist = await client.execute(
                "SLACK_FETCH_CONVERSATION_HISTORY", {"channel": cid, "limit": 50}, org_id
            )
            hdata = hist.get("data") or {}
            messages = _first_list(
                _dig(hdata, "response_data", "messages"), _dig(hdata, "messages")
            )
            text = "\n".join(
                m.get("text", "") for m in messages if isinstance(m, dict) and m.get("text")
            )
        except Exception:  # noqa: BLE001
            text = ""
        documents.append(
            SourceDocument(
                source_id=f"slack:{cid}",
                source_type="slack",
                org_id=org_id,
                external_id=cid,
                title=f"#{name}",
                text=text or f"#{name}",
                permissions=["source:all"],
            )
        )
    return documents


def _plain_text(data: Any) -> str:
    """Best-effort text extraction from a Composio file/content payload."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("text", "content", "body", "plain_text"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v
    return ""


_FETCHERS = {
    "notion": _fetch_notion,
    "googledrive": _fetch_googledrive,
    "slack": _fetch_slack,
}


async def sync_all_connections(
    org_id: str,
    session: Session,
    *,
    client: ComposioClient | None = None,
    qdrant_store: QdrantStore | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Auto-detect every active Composio connection for an org and ingest each
    one that OSAI knows how to read. Idempotent — safe to call on every connect."""
    client = client or get_default_composio_client()
    if not client.available():
        return {"status": "skipped", "reason": "composio not configured", "synced": []}

    connections = await client.list_connections(org_id)
    synced: list[dict[str, Any]] = []
    for conn in connections:
        toolkit = conn.get("toolkit")
        status = (conn.get("status") or "").upper()
        if status and status != "ACTIVE":
            continue
        if toolkit not in _FETCHERS:
            continue
        synced.append(
            await ingest_composio_toolkit(
                org_id, toolkit, session, client=client, qdrant_store=qdrant_store, limit=limit
            )
        )
    return {"status": "ok", "synced": synced}
