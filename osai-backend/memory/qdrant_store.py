from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from config import settings
from memory.embeddings import EmbeddingProvider, default_embedding_provider


class QdrantStore:
    def __init__(
        self,
        *,
        url: str = settings.qdrant_url,
        collection_name: str = settings.qdrant_collection,
        embedding_provider: EmbeddingProvider = default_embedding_provider,
        client: AsyncQdrantClient | None = None,
    ) -> None:
        self.url = url
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        self.client = client or AsyncQdrantClient(url=url, api_key=settings.qdrant_api_key)

    async def ensure_collection(self) -> None:
        collections = await self.client.get_collections()
        names = {collection.name for collection in collections.collections}
        want = self.embedding_provider.dimension
        if self.collection_name not in names:
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=want,
                    distance=models.Distance.COSINE,
                ),
            )
        else:
            # Fail fast on a dimension mismatch rather than silently degrading
            # retrieval: a collection built for N dims can't be queried with an
            # M-dim vector (e.g. switching Gemini 768 ↔ hash-fallback 64).
            have = _collection_vector_size(await self.client.get_collection(self.collection_name))
            if have is not None and have != want:
                raise RuntimeError(
                    f"Qdrant collection {self.collection_name!r} has vector size {have}, "
                    f"but the active embedding provider produces {want}-dim vectors. "
                    "Set OSAI_EMBEDDING_DIMENSION to match, or recreate the collection."
                )
        # Qdrant Cloud rejects filtering on an unindexed field; every search is
        # org-scoped, so ensure a keyword index on org_id. Idempotent.
        try:
            await self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="org_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass  # index already exists

    async def search(
        self, query_vector: list[float], org_id: str, limit: int = 8
    ) -> list[Any]:
        """Vector search scoped to an org. Returns scored points (.score, .payload)."""
        response = await self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=limit,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="org_id", match=models.MatchValue(value=org_id)
                    )
                ]
            ),
            with_payload=True,
        )
        return response.points

    async def upsert_chunks(self, chunks: list[dict[str, Any]]) -> int:
        if not chunks:
            return 0
        await self.ensure_collection()
        vectors = await self.embedding_provider.embed_texts(
            [str(chunk["text"]) for chunk in chunks]
        )
        points = [
            models.PointStruct(
                id=_stable_point_id(f"{chunk['org_id']}:{chunk['chunk_id']}"),
                vector=vector,
                payload=_chunk_payload(chunk),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await self.client.upsert(collection_name=self.collection_name, points=points)
        return len(points)

    async def delete_org(self, org_id: str) -> None:
        """Delete all vectors for an org (used when resetting workspace content)."""
        await self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="org_id", match=models.MatchValue(value=org_id)
                        )
                    ]
                )
            ),
        )

    async def set_document_payload(
        self, org_id: str, source_document_id: str, payload: dict[str, Any]
    ) -> None:
        """Overwrite payload keys on every chunk of one document (org-scoped).
        Used when a document's access changes after ingestion — permission
        grants live in the chunk payload, so retrieval reflects the change
        immediately without re-embedding."""
        await self.client.set_payload(
            collection_name=self.collection_name,
            payload=payload,
            points=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="org_id", match=models.MatchValue(value=org_id)
                        ),
                        models.FieldCondition(
                            key="source_document_id",
                            match=models.MatchValue(value=source_document_id),
                        ),
                    ]
                )
            ),
        )

    async def delete_source_type(self, org_id: str, source_type: str) -> None:
        """Delete all vectors for one connector within an org (e.g. every Google
        Drive chunk), used when a connector is reconnected with a different
        account so stale documents can't be retrieved."""
        await self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="org_id", match=models.MatchValue(value=org_id)
                        ),
                        models.FieldCondition(
                            key="source_type", match=models.MatchValue(value=source_type)
                        ),
                    ]
                )
            ),
        )


def _collection_vector_size(info: Any) -> int | None:
    """Extract the configured vector size from a Qdrant get_collection response,
    tolerating the single-vector and named-vector config shapes. Returns None if
    it can't be determined (then the caller skips the mismatch check)."""
    try:
        params = info.config.params.vectors
    except AttributeError:
        return None
    if hasattr(params, "size"):
        return int(params.size)
    if isinstance(params, dict) and params:
        first = next(iter(params.values()))
        return int(getattr(first, "size", 0)) or None
    return None


def _stable_point_id(namespaced_chunk_id: str) -> str:
    # Qdrant accepts UUID strings; uuid5 keeps point ids stable across re-syncs.
    # Caller namespaces by org (f"{org_id}:{chunk_id}") so two orgs that ingest
    # the same document do not collide and overwrite each other's vectors.
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, namespaced_chunk_id))


def _chunk_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(chunk.get("metadata") or {})
    return {
        "chunk_id": chunk["chunk_id"],
        "source_document_id": chunk["source_document_id"],
        "org_id": chunk["org_id"],
        "source_type": chunk["source_type"],
        "content_preview": chunk["content_preview"],
        "text": chunk["text"],
        "title": metadata.get("title"),
        "url": metadata.get("url"),
        "permissions": chunk.get("permissions", []),
        "data_tier": chunk.get("data_tier", "normal"),
        "department_id": chunk.get("department_id"),
    }


def get_default_qdrant_store() -> QdrantStore:
    return QdrantStore()
