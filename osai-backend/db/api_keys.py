"""Opaque, per-user API keys for agent-facing integrations."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from config import settings

_TOKEN_PREFIX = "osai_mcp_"


def issue_mcp_api_key() -> tuple[str, str]:
    """Return a display prefix and the one-time plaintext bearer token."""
    secret = secrets.token_urlsafe(32)
    token = f"{_TOKEN_PREFIX}{secret}"
    return f"{_TOKEN_PREFIX}{secret[:8]}", token


def hash_mcp_api_key(token: str) -> str:
    """Hash keys with the deployment secret as a pepper before persistence."""
    return hmac.new(settings.jwt_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def is_mcp_api_key(token: str) -> bool:
    return token.startswith(_TOKEN_PREFIX)
