"""member clearance tier on users and invites

Adds a per-member data-clearance tier (normal/amber/red). A member can only see
documents whose data_tier is at or below their clearance; admins see all.

Revision ID: 20260707_0006
Revises: 20260617_0005
Create Date: 2026-07-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260707_0006"
down_revision: str | Sequence[str] | None = "20260617_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("data_tier", sa.String(), nullable=False, server_default="normal"),
    )
    op.add_column(
        "invites",
        sa.Column("data_tier", sa.String(), nullable=False, server_default="normal"),
    )


def downgrade() -> None:
    op.drop_column("invites", "data_tier")
    op.drop_column("users", "data_tier")
