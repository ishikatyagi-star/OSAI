"""Persist organization decision logs.

Revision ID: 20260711_0012
Revises: 20260711_0011
"""

from alembic import op
import sqlalchemy as sa

revision = "20260711_0012"
down_revision = "20260711_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("impact", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("identified_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decisions_org_id", "decisions", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_decisions_org_id", table_name="decisions")
    op.drop_table("decisions")
