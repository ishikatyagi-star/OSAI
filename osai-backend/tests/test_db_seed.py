from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Base, ConnectorAccount, ConnectorRecord, Org, User
from db.repositories import list_integrations, seed_demo_data


def test_seed_demo_data_creates_core_records() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_demo_data(session)

        assert session.get(Org, "demo-org") is not None
        assert session.scalar(select(User).where(User.email == "admin@osai.local")) is not None
        assert session.query(ConnectorRecord).count() == 4
        assert session.query(ConnectorAccount).count() == 4
        assert len(list_integrations(session, "demo-org")) == 4
