"""users.token_version — session-token generation for JWT revocation

Revision ID: 20260713_0022
Revises: 20260712_0021
Create Date: 2026-07-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0022"
down_revision: str | Sequence[str] | None = "20260712_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
