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
import hashlib
import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from api.schemas.connector import SourceDocument
from config import settings
from connectors.composio_tool import (
    ComposioClient,
    composio_identity,
    get_default_composio_client,
)
from connectors.toolkit_map import to_native_key
from db.models import SourceDocumentRecord, now_utc
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

# Chunks embedded per request. Batching across documents cuts a 25-doc sync from
# ~25 embedding requests to a handful, staying under free-tier per-minute limits;
# the cap keeps peak memory bounded on the small instance.
_EMBED_BATCH_CHUNKS = 96


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


async def _download_url_allowed(url: str) -> bool:
    """Fail closed for provider-returned URLs before making a server-side request.

    Require HTTPS, an operator-approved host, and only globally routable DNS
    answers. Redirects remain disabled by httpx, so a trusted temporary URL
    cannot bounce the fetch toward an internal or metadata service.
    """
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if (
            parsed.scheme.casefold() != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
        ):
            return False
    except ValueError:
        return False

    allowed = settings.composio_download_host_list
    if not any(
        host == entry or (entry.startswith(".") and host.endswith(entry)) for entry in allowed
    ):
        return False
    if host in {"metadata", "metadata.google.internal"} or host.startswith("metadata."):
        return False

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            443,
            type=socket.SOCK_STREAM,
        )
        addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    except (OSError, ValueError):
        return False
    return bool(addresses) and all(address.is_global for address in addresses)


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
        if not await _download_url_allowed(url):
            return None
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
    *,
    composio_user_id: str | None = None,
    owner_user_id: str = "",
) -> None:
    """Detect a reconnect with a different external account and purge the old
    account's indexed data. Records the account identity (id + email) on the
    ConnectorAccount so the UI can show who's connected and what changed. Scoped
    to the connection owner (composio_user_id for the provider read, owner_user_id
    for the DB account row)."""
    try:
        identity = await client.connection_identity(toolkit, composio_user_id or org_id)
    except Exception:  # noqa: BLE001 — identity is best-effort; never block sync
        identity = None
    if not identity or not identity.get("id"):
        return

    account = ensure_connector_account(session, org_id, native_key, owner_user_id)
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


def _record_ingest_failure(
    session: Session,
    *,
    org_id: str,
    toolkit: str,
    error: str,
) -> dict[str, Any]:
    """Rollback partial relational work, then persist one actionable failure."""
    session.rollback()
    native_key = to_native_key(toolkit)
    account = ensure_connector_account(session, org_id, native_key)
    account.auth_state = "error"
    error = error[:2000]
    record_sync_result(
        session,
        org_id=org_id,
        connector_key=native_key,
        status="failed",
        documents_seen=0,
        documents_indexed=0,
        error=error,
    )
    return {"status": "failed", "error": error, "documents_indexed": 0}


async def ingest_composio_toolkit(
    org_id: str,
    toolkit: str,
    session: Session,
    *,
    client: ComposioClient | None = None,
    qdrant_store: QdrantStore | None = None,
    limit: int = 25,
    owner_user_id: str = "",
) -> dict[str, Any]:
    # Owner of the connection (empty = org-level/shared). Gated by the flag in one
    # place: callers may always pass the owner, but it only takes effect under
    # per-user connections. Reads then use this user's Composio identity and the
    # indexed docs are scoped to them (person-scoped) — searchable only by owner.
    owner = owner_user_id if settings.composio_per_user_connections else ""
    identity = composio_identity(org_id, owner or None)
    client = client or get_default_composio_client()
    qdrant_store = qdrant_store or get_default_qdrant_store()
    if not client.available():
        return _record_ingest_failure(
            session,
            org_id=org_id,
            toolkit=toolkit,
            error="Composio not configured",
        )

    fetcher = _FETCHERS.get(toolkit)
    if fetcher is None:
        return _record_ingest_failure(
            session,
            org_id=org_id,
            toolkit=toolkit,
            error=f"Ingestion not implemented for toolkit {toolkit!r}",
        )

    native_key = to_native_key(toolkit)
    # Everything below records a sync run no matter how it ends. Any unhandled
    # error here previously vanished (the background caller swallows exceptions),
    # so /sync-runs showed nothing at all — the user saw "Sync started" and then
    # silence. Now a failure always leaves a visible, explained failed run.
    stage = "account reconciliation"
    try:
        # Reconnect handling: if the org reconnected this toolkit with a
        # *different* external account, purge the previous account's documents so
        # counts and Ask reflect only the currently-connected account.
        await _handle_account_change(
            session, client, org_id, toolkit, native_key, qdrant_store,
            composio_user_id=identity, owner_user_id=owner,
        )
        stage = "provider fetch"
        documents = await fetcher(client, identity, limit)
        # Scope a per-user connection's documents to their owner (person-scoped),
        # so RAG returns them only to that user — even admins can't see them.
        if owner and documents:
            for doc in documents:
                doc.permissions = [f"user:{owner}"]
        stage = "document indexing"
        if documents:
            # Tier rules are keyed by the native connector key, so a
            # Composio-ingested doc is classified the same way a natively-synced
            # one would be, instead of always landing at the default tier.
            apply_tier_rules(session, org_id, native_key, documents)

        # Capture each doc's previously-embedded content hash BEFORE the upsert
        # overwrites metadata, so unchanged docs skip re-embedding (which is what
        # exhausts the embedding quota and burns the tiny CPU).
        prior_hashes = _prior_embedded_hashes(session, [d.source_id for d in documents])

        indexed = upsert_source_documents(session, documents)
        vector_error = None
        embedded = 0
        skipped_unchanged = 0
        # Batch chunks across documents into a few embed calls, not one per doc.
        # Free-tier embedding providers (Voyage/Gemini) rate-limit per minute, so
        # one request per document blows the limit (429) on any real sync. The
        # per-batch cap bounds memory so a big sync can't OOM the small instance.
        pending_chunks: list[dict[str, Any]] = []
        pending_doc_ids: set[str] = set()
        document_hashes: dict[str, str] = {}
        failed_doc_ids: set[str] = set()

        async def _flush() -> None:
            nonlocal vector_error
            if not pending_chunks:
                return
            try:
                await qdrant_store.upsert_chunks(list(pending_chunks))
            except Exception as exc:  # noqa: BLE001 — vectors shouldn't block sync
                logger.warning("Composio vector batch failed for %s: %s", toolkit, exc)
                # Surface the actual cause (embedding-provider HTTP status /
                # Qdrant dimension mismatch) instead of a generic message, so a
                # failed sync is diagnosable from /sync-runs without server logs.
                detail = str(exc).strip() or type(exc).__name__
                vector_error = f"Vector indexing failed: {detail[:240]}"
                failed_doc_ids.update(pending_doc_ids)
            pending_chunks.clear()
            pending_doc_ids.clear()

        for document in documents:
            await asyncio.sleep(0)
            # Don't embed documents whose "text" is just their own filename
            # (untranscribed media, skipped-large files): the vector carries no
            # content signal but still matches ~0.7 on unrelated queries.
            if not document.text.strip() or document.text.strip() == (
                document.title or ""
            ).strip():
                try:
                    await qdrant_store.delete_document(org_id, document.source_id)
                except Exception:  # noqa: BLE001 — cleanup is best-effort
                    pass
                continue
            content_hash = _content_hash(document.text)
            if prior_hashes.get(document.source_id) == content_hash:
                # Unchanged since the last successful embed; vectors already exist.
                _set_embedded_hash(session, document.source_id, content_hash)
                skipped_unchanged += 1
                continue
            document_hashes[document.source_id] = content_hash
            for chunk in chunks_for_documents([document]):
                pending_chunks.append(chunk)
                pending_doc_ids.add(document.source_id)
                if len(pending_chunks) == _EMBED_BATCH_CHUNKS:
                    await _flush()
        await _flush()
        for source_id, content_hash in document_hashes.items():
            if source_id in failed_doc_ids:
                continue
            _set_embedded_hash(session, source_id, content_hash)
            embedded += 1
    except Exception as exc:  # noqa: BLE001 — always leave a visible failed run
        logger.exception("Composio %s failed during %s", toolkit, stage)
        return _record_ingest_failure(
            session,
            org_id=org_id,
            toolkit=toolkit,
            error=f"{stage.capitalize()} failed: {exc}",
        )

    sync_status = "partial" if vector_error or not documents else "succeeded"
    record_sync_result(
        session,
        org_id=org_id,
        # Attribute to the native connector key so the single Integrations card
        # reflects the connection/sync (Composio `googledrive` -> `google_drive`).
        connector_key=to_native_key(toolkit),
        status=sync_status,
        documents_seen=len(documents),
        documents_indexed=indexed,
        error=vector_error,
        user_id=owner,
    )
    return {
        "status": sync_status,
        "toolkit": toolkit,
        "documents_seen": len(documents),
        "documents_indexed": indexed,
        "documents_embedded": embedded,
        "documents_skipped_unchanged": skipped_unchanged,
        "vector_error": vector_error,
    }


# ---------------------------------------------------------------------------
# Toolkit-specific fetchers — turn a connected app's content into SourceDocuments
# ---------------------------------------------------------------------------


def _content_hash(text: str) -> str:
    """Stable hash of a document's indexed text, used to skip re-embedding
    unchanged documents on subsequent syncs.

    The hash is namespaced by the active embedding provider (name/model/
    dimension) so that switching providers — whose vectors live in a different
    space and dimension — invalidates the cache and forces a re-embed, instead
    of leaving the index full of the previous provider's (now unqueryable)
    vectors. Re-embedding overwrites the same content-derived Qdrant point ids."""
    from memory.embeddings import default_embedding_provider as provider

    namespace = (
        f"{getattr(provider, 'name', '?')}:"
        f"{getattr(provider, 'model', '?')}:"
        f"{getattr(provider, 'dimension', '?')}"
    )
    return hashlib.sha256(f"{namespace}\x00{text}".encode("utf-8")).hexdigest()


def _prior_embedded_hashes(session: Session, source_ids: list[str]) -> dict[str, str]:
    """The content hash last successfully embedded for each source id (from the
    document's metadata), so an unchanged doc isn't re-embedded."""
    if not source_ids:
        return {}
    rows = (
        session.query(SourceDocumentRecord.id, SourceDocumentRecord.metadata_json)
        .filter(SourceDocumentRecord.id.in_(source_ids))
        .all()
    )
    out: dict[str, str] = {}
    for sid, meta in rows:
        h = (meta or {}).get("embedded_hash")
        if h:
            out[sid] = h
    return out


def _set_embedded_hash(session: Session, source_id: str, content_hash: str) -> None:
    """Record the content hash we just embedded, so the next sync can skip this
    doc if its text is unchanged. Best-effort: never fail a sync over bookkeeping."""
    record = session.get(SourceDocumentRecord, source_id)
    if record is None:
        return
    meta = dict(record.metadata_json or {})
    meta["embedded_hash"] = content_hash
    record.metadata_json = meta
    session.flush()


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
    if not url or not await _download_url_allowed(url):
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


async def _fetch_gmail(client: ComposioClient, org_id: str, limit: int) -> list[SourceDocument]:
    """Recent inbox emails, one document per message. Subject/sender land in the
    title so filename-only guards don't drop messages with short bodies."""
    res = await client.execute("GMAIL_FETCH_EMAILS", {"max_results": min(limit, 25)}, org_id)
    data = res.get("data") or {}
    messages = _first_list(
        _dig(data, "response_data", "messages"), _dig(data, "messages")
    )

    documents: list[SourceDocument] = []
    for msg in messages[:limit]:
        await asyncio.sleep(0)  # keep /health responsive during ingest
        if not isinstance(msg, dict):
            continue
        mid = msg.get("messageId") or msg.get("id")
        if not mid:
            continue
        subject = (msg.get("subject") or "").strip() or "(no subject)"
        sender = (msg.get("sender") or msg.get("from") or "").strip()
        body = ""
        for key in ("messageText", "messageBody", "snippet", "preview"):
            v = msg.get(key)
            if isinstance(v, str) and v.strip():
                body = v.strip()
                break
        header = f"From: {sender}\nSubject: {subject}" if sender else f"Subject: {subject}"
        documents.append(
            SourceDocument(
                source_id=f"gmail:{mid}",
                source_type="gmail",
                org_id=org_id,
                external_id=str(mid),
                title=subject,
                text=f"{header}\n\n{body}" if body else header,
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
}
SUPPORTED_INGESTION_TOOLKITS = frozenset(_FETCHERS)


async def sync_all_connections(
    org_id: str,
    session: Session,
    *,
    client: ComposioClient | None = None,
    qdrant_store: QdrantStore | None = None,
    limit: int = 25,
    owner_user_id: str = "",
) -> dict[str, Any]:
    """Auto-detect every active Composio connection for the caller and ingest each
    one OSAI can read. Scoped to the owner (per-user when enabled, else org-level).
    Idempotent — safe to call on every connect."""
    client = client or get_default_composio_client()
    if not client.available():
        return {"status": "skipped", "reason": "composio not configured", "synced": []}

    # composio_identity gates on the flag: per-user identity when enabled, else
    # org_id. Ingest re-gates the owner for document scoping.
    identity = composio_identity(org_id, owner_user_id or None)
    connections = await client.list_connections(identity)
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
                org_id,
                toolkit,
                session,
                client=client,
                qdrant_store=qdrant_store,
                limit=limit,
                owner_user_id=owner_user_id,
            )
        )
    return {"status": "ok", "synced": synced}
