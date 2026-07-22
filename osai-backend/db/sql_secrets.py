"""Encrypt SQL source credentials before they reach application storage."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from config import settings

SQL_DSN_CIPHERTEXT_PREFIX = "osai-fernet-v1:"


class SqlDsnSecretError(RuntimeError):
    """SQL source credentials cannot be encrypted or decrypted safely."""


def _keyring() -> MultiFernet:
    keys = settings.sql_dsn_encryption_key_list
    if not keys:
        raise SqlDsnSecretError("SQL DSN encryption keys are not configured.")
    try:
        return MultiFernet([Fernet(key.encode("ascii")) for key in keys])
    except (UnicodeEncodeError, ValueError) as exc:
        # Settings validates normal process startup. Keep this guard for tests
        # and runtime configuration mutation without ever echoing a key.
        raise SqlDsnSecretError("SQL DSN encryption keys are invalid.") from exc


def encrypt_sql_dsn(dsn: str) -> str:
    """Return an authenticated ciphertext using the primary configured key."""
    token = _keyring().encrypt(dsn.encode("utf-8")).decode("ascii")
    return f"{SQL_DSN_CIPHERTEXT_PREFIX}{token}"


def decrypt_sql_dsn(stored: str) -> str:
    """Decrypt one stored DSN, rejecting plaintext and tampered ciphertext."""
    if not stored.startswith(SQL_DSN_CIPHERTEXT_PREFIX):
        raise SqlDsnSecretError("Stored SQL DSN is not encrypted.")
    token = stored.removeprefix(SQL_DSN_CIPHERTEXT_PREFIX)
    try:
        return _keyring().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise SqlDsnSecretError("Stored SQL DSN cannot be decrypted.") from exc
