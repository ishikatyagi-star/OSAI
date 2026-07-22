from types import SimpleNamespace

from api.schemas.connector import SourceDocument
from memory.chunker import chunk_document
from memory.embeddings import HashEmbeddingProvider
from memory.qdrant_store import QdrantStore, _chunk_payload


class FakeQdrantClient:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.upserts: list[tuple[str, list[object]]] = []
        self.queries: list[dict] = []
        self.deletes: list[dict] = []
        self.payload_updates: list[dict] = []

    async def get_collections(self):
        return SimpleNamespace(collections=[])

    async def create_collection(self, collection_name: str, vectors_config) -> None:
        self.created.append(collection_name)

    async def upsert(self, collection_name: str, points: list[object]) -> None:
        self.upserts.append((collection_name, points))

    async def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return SimpleNamespace(points=[])

    async def delete(self, **kwargs) -> None:
        self.deletes.append(kwargs)

    async def set_payload(self, **kwargs) -> None:
        self.payload_updates.append(kwargs)


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


def _filter_values(selector) -> dict[str, object]:
    return {condition.key: condition.match.value for condition in selector.filter.must}


async def test_qdrant_reads_and_document_mutations_are_org_scoped() -> None:
    client = FakeQdrantClient()
    store = QdrantStore(
        collection_name="test_chunks",
        embedding_provider=HashEmbeddingProvider(dimension=8),
        client=client,
    )

    await store.search([0.0] * 8, "org-a")
    await store.set_document_payload("org-a", "doc-1", {"permissions": ["user:1"]})
    await store.delete_document("org-a", "doc-1")
    await store.delete_source_type("org-a", "slack")

    query_filter = client.queries[0]["query_filter"]
    assert {condition.key: condition.match.value for condition in query_filter.must} == {
        "org_id": "org-a"
    }
    assert _filter_values(client.payload_updates[0]["points"]) == {
        "org_id": "org-a",
        "source_document_id": "doc-1",
    }
    assert _filter_values(client.deletes[0]["points_selector"]) == {
        "org_id": "org-a",
        "source_document_id": "doc-1",
    }
    assert _filter_values(client.deletes[1]["points_selector"]) == {
        "org_id": "org-a",
        "source_type": "slack",
    }


async def test_qdrant_point_ids_are_namespaced_by_org() -> None:
    client = FakeQdrantClient()
    store = QdrantStore(
        collection_name="test_chunks",
        embedding_provider=HashEmbeddingProvider(dimension=8),
        client=client,
    )
    shared = {
        "chunk_id": "chunk-1",
        "source_document_id": "notion:page-1",
        "source_type": "notion",
        "content_preview": "Shared preview",
        "text": "The same source content",
    }

    await store.upsert_chunks(
        [{**shared, "org_id": "org-a"}, {**shared, "org_id": "org-b"}]
    )

    _, points = client.upserts[0]
    assert points[0].id != points[1].id
    assert {point.payload["org_id"] for point in points} == {"org-a", "org-b"}
