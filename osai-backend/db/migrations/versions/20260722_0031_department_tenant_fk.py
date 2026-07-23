"""Bind department references to their workspace at the database boundary.

Revision ID: 20260722_0031
Revises: 20260722_0030
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0031"
down_revision: str | Sequence[str] | None = "20260722_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REFERENCES = (
    ("users", "fk_users_department_id_departments", "RESTRICT"),
    ("invites", "fk_invites_department_id_departments", "RESTRICT"),
    ("source_documents", "fk_source_documents_department_id_departments", "RESTRICT"),
)


def _clear_cross_workspace_references(connection: sa.Connection, table: str) -> None:
    connection.execute(
        sa.text(
            f"""
            UPDATE {table}
            SET department_id = NULL
            WHERE department_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1
                FROM departments
                WHERE departments.org_id = {table}.org_id
                  AND departments.id = {table}.department_id
              )
            """
        )
    )
    remaining = int(
        connection.execute(
            sa.text(
                f"""
                SELECT COUNT(*)
                FROM {table}
                WHERE department_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM departments
                    WHERE departments.org_id = {table}.org_id
                      AND departments.id = {table}.department_id
                  )
                """
            )
        ).scalar_one()
    )
    if remaining:
        raise RuntimeError(
            f"Cannot enforce tenant-scoped departments: {remaining} invalid {table} row(s) remain."
        )


def _restore_sqlite_email_index(connection: sa.Connection) -> None:
    if connection.dialect.name == "sqlite":
        # SQLite cannot reflect expression indexes during Alembic batch table
        # recreation, so preserve the normalized-email invariant explicitly.
        connection.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_normalized "
                "ON users (lower(trim(email)))"
            )
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                "LOCK TABLE departments, users, invites, source_documents "
                "IN SHARE ROW EXCLUSIVE MODE"
            )
        )

    for table, _constraint, _ondelete in _REFERENCES:
        _clear_cross_workspace_references(connection, table)

    op.create_index(
        "uq_departments_org_id_id",
        "departments",
        ["org_id", "id"],
        unique=True,
    )
    for table, constraint, ondelete in _REFERENCES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(constraint, type_="foreignkey")
            batch_op.create_foreign_key(
                constraint,
                "departments",
                ["org_id", "department_id"],
                ["org_id", "id"],
                ondelete=ondelete,
            )
    _restore_sqlite_email_index(connection)


def downgrade() -> None:
    connection = op.get_bind()
    for table, constraint, _ondelete in reversed(_REFERENCES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(constraint, type_="foreignkey")
            batch_op.create_foreign_key(
                constraint,
                "departments",
                ["department_id"],
                ["id"],
                ondelete="SET NULL" if table == "invites" else "RESTRICT",
            )
    _restore_sqlite_email_index(connection)
    op.drop_index("uq_departments_org_id_id", table_name="departments")
