"""Ingest a user's documents from a Composio-connected app into OSAI's brain.

Flow: user connects an app via OAuth (POST /integrations/composio/connect/{tk}),
then this pulls their content through Composio's tools and indexes it into the
same RAG pipeline the native connectors use (Postgres source_documents + chunks
+ Qdrant vectors). No token-sharing — auth lives in the Composio connection.

Notion is implemented first; add other toolkits by extending `_FETCHERS`.
"""

from __future__ import annotations

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
        dl = await client.execute("GOOGLEDRIVE_DOWNLOAD_FILE", {"file_id": fid}, org_id)
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
                audio = base64.b64decode(v)
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
    try:
        await qdrant_store.upsert_chunks(chunks_for_documents(documents))
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
                source_id=f"{org_id}:notion:{page_id}",
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


async def _fetch_googledrive(
    client: ComposioClient, org_id: str, limit: int
) -> list[SourceDocument]:
    res = await client.execute("GOOGLEDRIVE_LIST_FILES", {"page_size": limit}, org_id)
    data = res.get("data") or {}
    files = _first_list(_dig(data, "response_data", "files"), _dig(data, "files"))

    documents: list[SourceDocument] = []
    for f in files[:limit]:
        fid = f.get("id")
        if not fid:
            continue
        name = f.get("name") or "Untitled"
        url = f.get("webViewLink") or f.get("web_view_link")
        text = ""
        metadata: dict[str, Any] = {}
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
            try:
                content = await client.execute(
                    "GOOGLEDRIVE_DOWNLOAD_FILE", {"file_id": fid}, org_id
                )
                text = _plain_text(content.get("data") or {})
            except Exception:  # noqa: BLE001
                text = ""
        documents.append(
            SourceDocument(
                source_id=f"{org_id}:gdrive:{fid}",
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
                source_id=f"{org_id}:slack:{cid}",
                source_type="slack",
                org_id=org_id,
                external_id=cid,
                title=f"#{name}",
                text=text or f"#{name}",
                permissions=["source:all"],
            )
        )
    return documents


async def _fetch_gmail(client: ComposioClient, org_id: str, limit: int) -> list[SourceDocument]:
    """Index a bounded set of recent messages from the connected Gmail account."""
    res = await client.execute(
        "GMAIL_FETCH_EMAILS", {"query": "newer_than:365d", "max_results": limit}, org_id
    )
    data = res.get("data") or {}
    messages = _first_list(
        _dig(data, "response_data", "messages"),
        _dig(data, "messages"),
        _dig(data, "response_data", "threads"),
        _dig(data, "threads"),
        data if isinstance(data, list) else None,
    )
    documents: list[SourceDocument] = []
    for message in messages[:limit]:
        message_id = message.get("id") or message.get("message_id") or message.get("threadId")
        if not message_id:
            continue
        payload = message.get("payload") or message
        headers = payload.get("headers") or []
        subject = next(
            (
                str(header.get("value"))
                for header in headers
                if isinstance(header, dict) and str(header.get("name", "")).lower() == "subject"
            ),
            "Untitled email",
        )
        sender = next(
            (
                str(header.get("value"))
                for header in headers
                if isinstance(header, dict) and str(header.get("name", "")).lower() == "from"
            ),
            None,
        )
        text = message.get("snippet") or payload.get("snippet") or subject
        documents.append(
            SourceDocument(
                source_id=f"{org_id}:gmail:{message_id}",
                source_type="gmail",
                org_id=org_id,
                external_id=str(message_id),
                title=subject,
                text=str(text),
                author=sender,
                permissions=["source:all"],
            )
        )
    return documents


async def _fetch_github(client: ComposioClient, org_id: str, limit: int) -> list[SourceDocument]:
    """Index repository metadata from the connected GitHub account."""
    res = await client.execute("GITHUB_LIST_REPOSITORIES", {"per_page": limit}, org_id)
    data = res.get("data") or {}
    repositories = _first_list(
        _dig(data, "response_data", "repositories"),
        _dig(data, "response_data", "items"),
        _dig(data, "repositories"),
        _dig(data, "items"),
        data if isinstance(data, list) else None,
    )
    documents: list[SourceDocument] = []
    for repository in repositories[:limit]:
        repo_id = repository.get("id") or repository.get("node_id") or repository.get("full_name")
        if not repo_id:
            continue
        title = repository.get("full_name") or repository.get("name") or "Untitled repository"
        description = repository.get("description") or "No repository description."
        text = "\n".join(
            value
            for value in (
                str(description),
                f"Language: {repository.get('language')}" if repository.get("language") else "",
                f"Default branch: {repository.get('default_branch')}" if repository.get("default_branch") else "",
            )
            if value
        )
        documents.append(
            SourceDocument(
                source_id=f"{org_id}:github:{repo_id}",
                source_type="github",
                org_id=org_id,
                external_id=str(repo_id),
                title=str(title),
                url=repository.get("html_url"),
                text=text,
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
    "gmail": _fetch_gmail,
    "github": _fetch_github,
}


def supports_sync(toolkit: str) -> bool:
    return toolkit.lower() in _FETCHERS


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
        if not toolkit or (status and status != "ACTIVE"):
            continue
        account = ensure_connector_account(session, org_id, to_native_key(toolkit))
        config = dict(account.config or {})
        config["account_external_id"] = conn.get("id")
        config["account_email"] = conn.get("email")
        account.config = config
        account.auth_state = "connected"
        if toolkit not in _FETCHERS:
            synced.append({"toolkit": toolkit, "status": "connected", "sync": False})
            continue
        synced.append(
            await ingest_composio_toolkit(
                org_id, toolkit, session, client=client, qdrant_store=qdrant_store, limit=limit
            )
        )
    session.commit()
    return {"status": "ok", "synced": synced}
