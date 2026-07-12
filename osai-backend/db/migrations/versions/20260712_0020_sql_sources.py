"""sql_sources — read-only structured data sources for SQL answers

Revision ID: 20260712_0020
Revises: 20260712_0019
Create Date: 2026-07-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260712_0020"
down_revision: str | Sequence[str] | None = "20260712_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sql_sources",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("dsn", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sql_sources")
