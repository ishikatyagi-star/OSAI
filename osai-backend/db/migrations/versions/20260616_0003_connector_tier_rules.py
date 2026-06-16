"""connector_accounts.tier_rules

Revision ID: 20260616_0003
Revises: 45f9fa554d73
Create Date: 2026-06-16
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260616_0003"
down_revision: str | Sequence[str] | None = "45f9fa554d73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connector_accounts",
        sa.Column("tier_rules", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("connector_accounts", "tier_rules")
