"""automations table

Revision ID: 20260617_0005
Revises: 20260617_0004
Create Date: 2026-06-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_0005"
down_revision: str | Sequence[str] | None = "20260617_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("cadence", sa.String(), nullable=False, server_default="manual"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_automations_org_id"), "automations", ["org_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_automations_org_id"), table_name="automations")
    op.drop_table("automations")
