from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.schemas.connector import SourceDocument
from db.models import Base, Chunk, SourceDocumentRecord
from db.repositories import seed_demo_data, upsert_source_documents


def test_seed_and_upsert_composio_document() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_demo_data(session)
        indexed = upsert_source_documents(
            session,
            [
                SourceDocument(
                    source_id="notion:page-1",
                    source_type="notion",
                    org_id="demo-org",
                    external_id="page-1",
                    title="Composio page",
                    text="Indexed through Composio.",
                    url="https://notion.so/page-1",
                )
            ],
        )
        session.commit()
        assert indexed == 1
        assert session.query(SourceDocumentRecord).count() == 1
        assert session.query(Chunk).count() == 1
