"""Normalize user email identities and enforce case-insensitive uniqueness.

Revision ID: 20260722_0029
Revises: 20260722_0028
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0029"
down_revision: str | Sequence[str] | None = "20260722_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLLISION_QUERY = sa.text(
    """
    SELECT COUNT(*)
    FROM (
        SELECT lower(trim(email)) AS normalized_email
        FROM users
        GROUP BY lower(trim(email))
        HAVING COUNT(*) > 1
    ) AS normalized_email_collisions
    """
)


def _assert_no_normalized_email_collisions(connection: sa.Connection) -> None:
    collision_groups = int(connection.execute(_COLLISION_QUERY).scalar_one())
    if collision_groups:
        raise RuntimeError(
            "Cannot normalize user emails: found "
            f"{collision_groups} normalized identity collision group(s). "
            "Merge or remove duplicate accounts, then rerun migration 20260722_0029."
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # Prevent a user write from racing the collision preflight and index build.
        connection.execute(sa.text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))

    # This must run before either the UPDATE or CREATE INDEX so collisions abort
    # with a count-only remediation message rather than leaking an email in a DB error.
    _assert_no_normalized_email_collisions(connection)
    connection.execute(
        sa.text(
            """
            UPDATE users
            SET email = lower(trim(email))
            WHERE email <> lower(trim(email))
            """
        )
    )
    op.create_index(
        "uq_users_email_normalized",
        "users",
        [sa.text("lower(trim(email))")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_email_normalized", table_name="users")
