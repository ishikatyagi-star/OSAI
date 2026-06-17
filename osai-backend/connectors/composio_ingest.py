"""Ingest a user's documents from a Composio-connected app into OSAI's brain.

Flow: user connects an app via OAuth (POST /integrations/composio/connect/{tk}),
then this pulls their content through Composio's tools and indexes it into the
same RAG pipeline the native connectors use (Postgres source_documents + chunks
+ Qdrant vectors). No token-sharing — auth lives in the Composio connection.

Notion is implemented first; add other toolkits by extending `_FETCHERS`.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from api.schemas.connector import SourceDocument
from connectors.composio_tool import ComposioClient, get_default_composio_client
from connectors.toolkit_map import to_native_key
from db.repositories import chunks_for_documents, record_sync_result, upsert_source_documents
from memory.qdrant_store import QdrantStore, get_default_qdrant_store

logger = logging.getLogger("osai.composio.ingest")


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

    try:
        documents = await fetcher(client, org_id, limit)
    except Exception as exc:  # noqa: BLE001
        logger.error("Composio ingest %s failed: %s", toolkit, exc)
        return {"status": "failed", "error": str(exc), "documents_indexed": 0}

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
        try:
            content = await client.execute("GOOGLEDRIVE_DOWNLOAD_FILE", {"file_id": fid}, org_id)
            text = _plain_text(content.get("data") or {})
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
