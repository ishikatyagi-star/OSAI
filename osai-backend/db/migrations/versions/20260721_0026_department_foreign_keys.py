"""Enforce department references at the database boundary.

Revision ID: 20260721_0026
Revises: 20260721_0025
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0026"
down_revision: str | Sequence[str] | None = "20260721_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _clear_invalid_department_ids(table: str) -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE {table}
            SET department_id = NULL
            WHERE department_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1
                FROM departments
                WHERE departments.id = {table}.department_id
                  AND departments.org_id = {table}.org_id
              )
            """
        )
    )


def upgrade() -> None:
    for table in ("users", "invites", "source_documents"):
        _clear_invalid_department_ids(table)

    with op.batch_alter_table("users") as batch_op:
        batch_op.create_foreign_key(
            "fk_users_department_id_departments",
            "departments",
            ["department_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("invites") as batch_op:
        batch_op.create_foreign_key(
            "fk_invites_department_id_departments",
            "departments",
            ["department_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("source_documents") as batch_op:
        batch_op.create_foreign_key(
            "fk_source_documents_department_id_departments",
            "departments",
            ["department_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("source_documents") as batch_op:
        batch_op.drop_constraint(
            "fk_source_documents_department_id_departments",
            type_="foreignkey",
        )
    with op.batch_alter_table("invites") as batch_op:
        batch_op.drop_constraint(
            "fk_invites_department_id_departments",
            type_="foreignkey",
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint(
            "fk_users_department_id_departments",
            type_="foreignkey",
        )
