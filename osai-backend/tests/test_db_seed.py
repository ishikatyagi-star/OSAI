from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from connectors.notion import NotionConnector
from db.models import Base, Chunk, SourceDocumentRecord
from db.repositories import seed_demo_data, upsert_source_documents
from tests.test_notion_connector import FakeNotionClient


def test_seed_and_upsert_notion_documents() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_demo_data(session)

    async def run_sync() -> None:
        connector = NotionConnector(token="secret_test", client=FakeNotionClient())
        result = await connector.sync("demo-org")
        with Session(engine) as session:
            indexed = upsert_source_documents(session, result.documents)
            session.commit()
            assert indexed == 1
            assert session.query(SourceDocumentRecord).count() == 1
            assert session.query(Chunk).count() == 1

    import asyncio

    asyncio.run(run_sync())
