"""Per-user connector accounts: add user_id and a (org, user, connector) unique.

Under composio_per_user_connections the same connector exists once per user in an
org, so ConnectorAccount uniqueness must include the owner. user_id defaults to
"" (org-level / shared) so the constraint also dedupes legacy org-level rows.
Existing duplicates (from the pre-FK-fix era) are collapsed before the unique
constraint is added.

Revision ID: 20260723_0033
Revises: 20260722_0032
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0033"
down_revision: str | Sequence[str] | None = "20260722_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "uq_connector_accounts_org_user_key"


def upgrade() -> None:
    op.add_column(
        "connector_accounts",
        sa.Column("user_id", sa.String(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_connector_accounts_user_id", "connector_accounts", ["user_id"]
    )

    # Collapse duplicate (org_id, user_id, connector_key) rows before enforcing
    # uniqueness — keep the most recently updated (prefer the live account), drop
    # the rest, so a legacy duplicate can't fail the constraint. Window function
    # is portable across Postgres and SQLite (>=3.25).
    op.execute(
        """
        DELETE FROM connector_accounts
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY org_id, user_id, connector_key
                    ORDER BY updated_at DESC, id DESC
                ) AS rn
                FROM connector_accounts
            ) ranked
            WHERE ranked.rn > 1
        )
        """
    )

    op.create_unique_constraint(
        _CONSTRAINT,
        "connector_accounts",
        ["org_id", "user_id", "connector_key"],
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "connector_accounts", type_="unique")
    op.drop_index("ix_connector_accounts_user_id", table_name="connector_accounts")
    op.drop_column("connector_accounts", "user_id")
