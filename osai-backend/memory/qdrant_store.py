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
        self.client = client or AsyncQdrantClient(url=url)

    async def ensure_collection(self) -> None:
        collections = await self.client.get_collections()
        names = {collection.name for collection in collections.collections}
        if self.collection_name in names:
            return
        await self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=self.embedding_provider.dimension,
                distance=models.Distance.COSINE,
            ),
        )

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
                id=_stable_point_id(str(chunk["chunk_id"])),
                vector=vector,
                payload=_chunk_payload(chunk),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await self.client.upsert(collection_name=self.collection_name, points=points)
        return len(points)


def _stable_point_id(chunk_id: str) -> str:
    # Qdrant accepts UUID strings; uuid5 keeps point ids stable across re-syncs.
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


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
    }


def get_default_qdrant_store() -> QdrantStore:
    return QdrantStore()
