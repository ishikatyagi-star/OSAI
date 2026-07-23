"""Encrypt SQL source DSNs and enforce ciphertext storage.

Revision ID: 20260722_0032
Revises: 20260722_0031
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.engine import Connection

from config import settings

revision: str = "20260722_0032"
down_revision: str | Sequence[str] | None = "20260722_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREFIX = "osai-fernet-v1:"
_CONSTRAINT = "ck_sql_sources_dsn_encrypted"


def _keyring(keys: Sequence[str]) -> MultiFernet:
    if not keys:
        raise RuntimeError(
            "OSAI_SQL_DSN_ENCRYPTION_KEYS is required to migrate stored SQL sources."
        )
    try:
        return MultiFernet([Fernet(key.encode("ascii")) for key in keys])
    except (UnicodeEncodeError, ValueError) as exc:
        raise RuntimeError("OSAI_SQL_DSN_ENCRYPTION_KEYS contains an invalid Fernet key.") from exc


def _encrypt_existing_dsns(connection: Connection, keys: Sequence[str]) -> None:
    rows = connection.execute(sa.text("SELECT id, dsn FROM sql_sources")).mappings().all()
    if not rows:
        return
    ring = _keyring(keys)
    for row in rows:
        stored = row["dsn"]
        if stored.startswith(_PREFIX):
            try:
                plaintext = ring.decrypt(stored.removeprefix(_PREFIX).encode("ascii"))
            except (InvalidToken, UnicodeEncodeError) as exc:
                raise RuntimeError(
                    "A stored SQL source cannot be decrypted with the configured key ring."
                ) from exc
        else:
            plaintext = stored.encode("utf-8")
        encrypted = _PREFIX + ring.encrypt(plaintext).decode("ascii")
        connection.execute(
            sa.text("UPDATE sql_sources SET dsn = :dsn WHERE id = :source_id"),
            {"dsn": encrypted, "source_id": row["id"]},
        )


def _decrypt_existing_dsns(connection: Connection, keys: Sequence[str]) -> None:
    rows = connection.execute(sa.text("SELECT id, dsn FROM sql_sources")).mappings().all()
    encrypted_rows = [row for row in rows if row["dsn"].startswith(_PREFIX)]
    if not encrypted_rows:
        return
    ring = _keyring(keys)
    for row in encrypted_rows:
        try:
            plaintext = ring.decrypt(row["dsn"].removeprefix(_PREFIX).encode("ascii")).decode(
                "utf-8"
            )
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise RuntimeError(
                "A stored SQL source cannot be decrypted with the configured key ring."
            ) from exc
        connection.execute(
            sa.text("UPDATE sql_sources SET dsn = :dsn WHERE id = :source_id"),
            {"dsn": plaintext, "source_id": row["id"]},
        )


def upgrade() -> None:
    _encrypt_existing_dsns(op.get_bind(), settings.sql_dsn_encryption_key_list)
    # Batch mode recreates the table on SQLite and emits a normal ALTER on
    # PostgreSQL, keeping CI's zero-to-head migration path representative.
    with op.batch_alter_table("sql_sources") as batch_op:
        batch_op.create_check_constraint(_CONSTRAINT, "dsn LIKE 'osai-fernet-v1:%'")


def downgrade() -> None:
    with op.batch_alter_table("sql_sources") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="check")
    _decrypt_existing_dsns(op.get_bind(), settings.sql_dsn_encryption_key_list)
