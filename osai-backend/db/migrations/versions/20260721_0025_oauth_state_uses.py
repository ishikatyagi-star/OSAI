"""Persist single-use OAuth callback state.

Revision ID: 20260721_0025
Revises: 20260721_0024
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0025"
down_revision: str | Sequence[str] | None = "20260721_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_state_uses",
        sa.Column("jti_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("jti_hash"),
    )
    op.create_index(
        op.f("ix_oauth_state_uses_expires_at"),
        "oauth_state_uses",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_state_uses_expires_at"), table_name="oauth_state_uses")
    op.drop_table("oauth_state_uses")
