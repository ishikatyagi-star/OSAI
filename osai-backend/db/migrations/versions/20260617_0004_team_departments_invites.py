"""departments + invites + users.department_id

Revision ID: 20260617_0004
Revises: 20260616_0003
Create Date: 2026-06-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_0004"
down_revision: str | Sequence[str] | None = "20260616_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False, server_default="#6a4cf5"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_departments_org_id"), "departments", ["org_id"], unique=False)

    op.create_table(
        "invites",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("department_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_invites_org_id"), "invites", ["org_id"], unique=False)
    op.create_index(op.f("ix_invites_email"), "invites", ["email"], unique=False)
    op.create_index(op.f("ix_invites_status"), "invites", ["status"], unique=False)
    op.create_index(op.f("ix_invites_token"), "invites", ["token"], unique=False)

    op.add_column("users", sa.Column("department_id", sa.String(), nullable=True))
    op.create_index(op.f("ix_users_department_id"), "users", ["department_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_department_id"), table_name="users")
    op.drop_column("users", "department_id")
    op.drop_index(op.f("ix_invites_token"), table_name="invites")
    op.drop_index(op.f("ix_invites_status"), table_name="invites")
    op.drop_index(op.f("ix_invites_email"), table_name="invites")
    op.drop_index(op.f("ix_invites_org_id"), table_name="invites")
    op.drop_table("invites")
    op.drop_index(op.f("ix_departments_org_id"), table_name="departments")
    op.drop_table("departments")
