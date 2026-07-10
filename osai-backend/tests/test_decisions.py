from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, DecisionRecord, Org


def test_decision_record_is_tenant_scoped():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([Org(id="org-a", name="A"), Org(id="org-b", name="B")])
    session.add(DecisionRecord(org_id="org-a", title="Adopt OSAI", tags=["platform"]))
    session.commit()

    rows = session.query(DecisionRecord).filter(DecisionRecord.org_id == "org-b").all()
    assert rows == []
