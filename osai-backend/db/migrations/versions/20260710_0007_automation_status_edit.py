"""automation status, updated_at, connector snapshot

Revision ID: 20260710_0007
Revises: 20260707_0006
Create Date: 2026-07-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_0007"
down_revision: str | Sequence[str] | None = "20260707_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "automations",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )
    op.add_column(
        "automations",
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("automations", sa.Column("last_connectors", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("automations", "last_connectors")
    op.drop_column("automations", "updated_at")
    op.drop_column("automations", "status")
