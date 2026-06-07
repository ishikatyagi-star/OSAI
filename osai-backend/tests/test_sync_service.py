from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from connectors.sync_service import sync_connector
from db.models import Base, SyncRun
from db.repositories import seed_demo_data


class FailingQdrantStore:
    async def upsert_chunks(self, chunks: list[dict[str, object]]) -> int:
        raise RuntimeError("qdrant offline")


async def test_sync_records_vector_error_without_failing_source_sync(monkeypatch) -> None:
    from connectors.notion import NotionConnector
    from connectors.registry import connector_registry
    from tests.test_notion_connector import FakeNotionClient

    connector_registry.register(NotionConnector(token="secret_test", client=FakeNotionClient()))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_demo_data(session)
        result = await sync_connector("notion", "demo-org", session, FailingQdrantStore())
        run = session.query(SyncRun).first()

    assert result["status"] == "succeeded"
    assert result["documents_indexed"] == 1
    assert result["vectors_indexed"] == 0
    assert result["vector_error"] == "qdrant offline"
    assert run is not None
    assert run.error == "qdrant offline"
