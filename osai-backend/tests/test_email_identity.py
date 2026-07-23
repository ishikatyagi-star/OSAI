"""Normalized email is a single, fail-closed identity boundary."""

from __future__ import annotations

from importlib import import_module
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes.auth import LoginRequest, login
from api.routes.slack_ask import _mapped_user
from config import settings
from db.models import Base, Org, User


@pytest.fixture
def sqlite_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with testing_session() as session:
        yield session
    engine.dispose()


def _insert_legacy_collision(session: Session) -> str:
    # Simulate a pre-0029 database: the old exact-value constraint allowed these
    # two rows, while the normalized expression index does not.
    session.execute(text("DROP INDEX uq_users_email_normalized"))
    org = Org(name="Legacy identity collision")
    session.add(org)
    session.flush()
    session.execute(
        User.__table__.insert(),
        [
            {
                "id": "legacy-email-a",
                "org_id": org.id,
                "email": "Legacy@Example.TEST",
                "display_name": "Legacy A",
            },
            {
                "id": "legacy-email-b",
                "org_id": org.id,
                "email": " legacy@example.test ",
                "display_name": "Legacy B",
            },
        ],
    )
    session.commit()
    return org.id


@pytest.mark.asyncio
async def test_auth_and_slack_fail_closed_for_legacy_email_collision(
    sqlite_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = _insert_legacy_collision(sqlite_db)
    monkeypatch.setattr(settings, "email_login_enabled", True)

    with pytest.raises(HTTPException) as login_error:
        await login(LoginRequest(email="LEGACY@example.test"), sqlite_db, Response())
    assert login_error.value.status_code == 401
    assert login_error.value.detail == "Invalid credentials"

    with (
        patch(
            "api.routes.slack_ask._slack_user_email",
            new=AsyncMock(return_value=" Legacy@Example.Test "),
        ),
        pytest.raises(HTTPException) as slack_error,
    ):
        await _mapped_user(sqlite_db, org_id, "U-legacy")
    assert slack_error.value.status_code == 403
    assert slack_error.value.detail == "Slack user is not linked to this workspace."


def test_email_migration_collision_error_is_count_only_and_pii_safe(sqlite_db: Session) -> None:
    _insert_legacy_collision(sqlite_db)
    migration = import_module("db.migrations.versions.20260722_0029_normalize_user_emails")

    with pytest.raises(RuntimeError) as error:
        migration._assert_no_normalized_email_collisions(sqlite_db.connection())

    message = str(error.value)
    assert "1 normalized identity collision group" in message
    assert "legacy@example.test" not in message.lower()
