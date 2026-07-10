"""Config normalization (deploy robustness)."""

from __future__ import annotations

import pytest

from config import Settings


def test_database_url_gets_psycopg_driver():
    # Managed providers hand out these; we need the psycopg driver prefix.
    assert (
        Settings(database_url="postgres://u:p@h:5432/db").database_url
        == "postgresql+psycopg://u:p@h:5432/db"
    )
    assert (
        Settings(database_url="postgresql://u:p@h:5432/db").database_url
        == "postgresql+psycopg://u:p@h:5432/db"
    )


def test_already_psycopg_url_unchanged():
    url = "postgresql+psycopg://u:p@h:5432/db"
    assert Settings(database_url=url).database_url == url


def test_production_requires_real_embeddings():
    with pytest.raises(ValueError, match="OSAI_GEMINI_API_KEY"):
        Settings(
            env="production",
            jwt_secret="x" * 32,
            zoom_webhook_secret="zoom-secret",
            gemini_api_key=None,
        )
