from types import SimpleNamespace

from api.schemas.connector import SourceDocument
from memory.chunker import chunk_document
from memory.embeddings import HashEmbeddingProvider
from memory.qdrant_store import QdrantStore, _chunk_payload


class FakeQdrantClient:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.upserts: list[tuple[str, list[object]]] = []

    async def get_collections(self):
        return SimpleNamespace(collections=[])

    async def create_collection(self, collection_name: str, vectors_config) -> None:
        self.created.append(collection_name)

    async def upsert(self, collection_name: str, points: list[object]) -> None:
        self.upserts.append((collection_name, points))


async def test_hash_embeddings_are_deterministic_and_normalized() -> None:
    provider = HashEmbeddingProvider(dimension=8)
    first = (await provider.embed_texts(["Launch Notion sync"]))[0]
    second = (await provider.embed_texts(["Launch Notion sync"]))[0]

    assert first == second
    assert len(first) == 8
    assert any(value != 0 for value in first)


def test_chunk_payload_contains_permission_filters() -> None:
    document = SourceDocument(
        source_id="notion:page-1",
        source_type="notion",
        org_id="demo-org",
        external_id="page-1",
        title="Pilot Notes",
        text="Launch Notion sync",
        permissions=["notion:page:page-1"],
        data_tier="amber",
    )
    chunk = chunk_document(document)[0]
    payload = _chunk_payload(chunk)

    assert payload["org_id"] == "demo-org"
    assert payload["permissions"] == ["notion:page:page-1"]
    assert payload["data_tier"] == "amber"
    assert payload["title"] == "Pilot Notes"


async def test_qdrant_store_upserts_points() -> None:
    client = FakeQdrantClient()
    store = QdrantStore(
        collection_name="test_chunks",
        embedding_provider=HashEmbeddingProvider(dimension=8),
        client=client,
    )
    document = SourceDocument(
        source_id="notion:page-1",
        source_type="notion",
        org_id="demo-org",
        external_id="page-1",
        title="Pilot Notes",
        text="Launch Notion sync",
        permissions=["notion:page:page-1"],
    )

    count = await store.upsert_chunks(chunk_document(document))

    assert count == 1
    assert client.created == ["test_chunks"]
    collection_name, points = client.upserts[0]
    assert collection_name == "test_chunks"
    assert points[0].payload["source_document_id"] == "notion:page-1"
