from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from config import settings
from db.models import Base, Department, Invite, Org, SourceDocumentRecord, User

_BACKEND = Path(__file__).parents[1]


def _engine(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'department-fk.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def _seed(session: Session) -> None:
    session.add_all([Org(id="org-a", name="A"), Org(id="org-b", name="B")])
    session.flush()
    session.add(Department(id="dept-a", org_id="org-a", name="A department"))
    session.commit()


def _reference(kind: str, *, row_id: str, org_id: str, department_id: str):
    if kind == "users":
        return User(
            id=row_id,
            org_id=org_id,
            email=f"{row_id}@example.test",
            display_name=row_id,
            role="member",
            department_id=department_id,
        )
    if kind == "invites":
        return Invite(
            id=row_id,
            org_id=org_id,
            email=f"{row_id}@example.test",
            department_id=department_id,
            token=f"token-{row_id}",
        )
    return SourceDocumentRecord(
        id=row_id,
        org_id=org_id,
        source_type="test",
        external_id=row_id,
        title=row_id,
        text="body",
        department_id=department_id,
        ingested_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("kind", ["users", "invites", "source_documents"])
def test_database_rejects_cross_workspace_department_references(tmp_path, kind: str):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        _seed(session)
        session.add(
            _reference(kind, row_id=f"valid-{kind}", org_id="org-a", department_id="dept-a")
        )
        session.commit()

        session.add(
            _reference(kind, row_id=f"foreign-{kind}", org_id="org-b", department_id="dept-a")
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    foreign_keys = inspect(engine).get_foreign_keys(kind)
    assert any(
        fk["constrained_columns"] == ["org_id", "department_id"]
        and fk["referred_columns"] == ["org_id", "id"]
        for fk in foreign_keys
    )
    engine.dispose()


def test_postgresql_ddl_compiles_tenant_scoped_department_foreign_keys():
    dialect = postgresql.dialect()
    for model in (User, Invite, SourceDocumentRecord):
        ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
        assert (
            "FOREIGN KEY(org_id, department_id) "
            "REFERENCES departments (org_id, id) ON DELETE RESTRICT"
        ) in ddl
    index = next(
        index
        for index in Department.__table__.indexes
        if index.name == "uq_departments_org_id_id"
    )
    assert str(CreateIndex(index).compile(dialect=dialect)) == (
        "CREATE UNIQUE INDEX uq_departments_org_id_id ON departments (org_id, id)"
    )


def test_migration_cleans_legacy_cross_workspace_references_and_round_trips(
    tmp_path, monkeypatch
):
    url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config(str(_BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND / "db" / "migrations"))
    command.upgrade(config, "20260722_0030")

    engine = create_engine(url)
    with engine.begin() as connection:
        now = datetime.now(UTC).isoformat()
        connection.execute(
            text(
                "INSERT INTO orgs (id, name, data_routing, created_at) "
                "VALUES (:a, 'A', '{}', :now), (:b, 'B', '{}', :now)"
            ),
            {"a": "org-a", "b": "org-b", "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO departments (id, org_id, name, color, created_at) "
                "VALUES ('dept-a', 'org-a', 'A department', '#000000', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, org_id, email, display_name, role, department_id, permissions, "
                "data_tier, token_version, created_at) VALUES "
                "('user-b', 'org-b', 'b@example.test', 'B', 'member', 'dept-a', "
                "'[]', 'normal', 0, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO invites "
                "(id, org_id, email, role, department_id, data_tier, status, token, created_at) "
                "VALUES ('invite-b', 'org-b', 'invite@example.test', 'member', 'dept-a', "
                "'normal', 'pending', 'token', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO source_documents "
                "(id, org_id, source_type, external_id, title, text, metadata, permissions, "
                "data_tier, department_id, ingested_at) VALUES "
                "('doc-b', 'org-b', 'test', 'doc-b', 'Doc', 'body', '{}', '[]', "
                "'normal', 'dept-a', :now)"
            ),
            {"now": now},
        )
    engine.dispose()

    command.upgrade(config, "20260722_0031")
    engine = create_engine(url)
    with engine.connect() as connection:
        for table in ("users", "invites", "source_documents"):
            assert connection.execute(
                text(f"SELECT department_id FROM {table}")
            ).scalar_one() is None
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "20260722_0031"
        )
        assert connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND name = 'uq_users_email_normalized'"
            )
        ).scalar_one() == "uq_users_email_normalized"
    engine.dispose()

    command.downgrade(config, "20260722_0030")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND name = 'uq_users_email_normalized'"
            )
        ).scalar_one() == "uq_users_email_normalized"
    engine.dispose()
    command.upgrade(config, "20260722_0031")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "20260722_0031"
        )
    engine.dispose()
