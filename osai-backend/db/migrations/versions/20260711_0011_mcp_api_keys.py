"""Add per-user MCP API keys.

Revision ID: 20260711_0011
Revises: 20260711_0010
"""

from alembic import op
import sqlalchemy as sa

revision = "20260711_0011"
down_revision = "20260711_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_api_keys",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("token_prefix", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_mcp_api_keys_org_id", "mcp_api_keys", ["org_id"])
    op.create_index("ix_mcp_api_keys_user_id", "mcp_api_keys", ["user_id"])
    op.create_index("ix_mcp_api_keys_token_prefix", "mcp_api_keys", ["token_prefix"])
    op.create_index("ix_mcp_api_keys_token_hash", "mcp_api_keys", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_mcp_api_keys_token_hash", table_name="mcp_api_keys")
    op.drop_index("ix_mcp_api_keys_token_prefix", table_name="mcp_api_keys")
    op.drop_index("ix_mcp_api_keys_user_id", table_name="mcp_api_keys")
    op.drop_index("ix_mcp_api_keys_org_id", table_name="mcp_api_keys")
    op.drop_table("mcp_api_keys")
