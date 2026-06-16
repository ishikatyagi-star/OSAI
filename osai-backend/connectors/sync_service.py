from sqlalchemy.orm import Session

from connectors.registry import connector_registry
from db.repositories import (
    apply_tier_rules,
    chunks_for_documents,
    record_sync_result,
    upsert_source_documents,
)
from memory.qdrant_store import QdrantStore, get_default_qdrant_store


async def sync_connector(
    connector_key: str,
    org_id: str,
    session: Session,
    qdrant_store: QdrantStore | None = None,
) -> dict[str, object]:
    connector = connector_registry.get(connector_key)
    qdrant_store = qdrant_store or get_default_qdrant_store()
    result = await connector.sync(org_id)
    indexed = 0
    vector_indexed = 0
    vector_error = None
    if result.documents:
        # Apply per-info sensitivity overrides before persisting/indexing so that
        # e.g. a single "red" Drive folder is classified even if the connector
        # tagged everything "normal".
        apply_tier_rules(session, org_id, connector_key, result.documents)
        indexed = upsert_source_documents(session, result.documents)
        try:
            vector_indexed = await qdrant_store.upsert_chunks(
                chunks_for_documents(result.documents)
            )
        except Exception as exc:  # Qdrant should not block source sync in local pilot mode.
            vector_error = str(exc)
    run = record_sync_result(
        session,
        org_id=org_id,
        connector_key=connector_key,
        status=result.status,
        documents_seen=len(result.documents),
        documents_indexed=indexed,
        error=result.error or vector_error,
    )
    return {
        "id": run.id,
        "connector_key": connector_key,
        "status": result.status,
        "documents_seen": len(result.documents),
        "documents_indexed": indexed,
        "vectors_indexed": vector_indexed,
        "vector_error": vector_error,
        "error": result.error,
    }
