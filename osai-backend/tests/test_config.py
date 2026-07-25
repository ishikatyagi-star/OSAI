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


def test_recurring_scheduler_modes_are_mutually_exclusive():
    with pytest.raises(ValueError, match="Only one recurring-automation scheduler"):
        Settings(automations_cron_enabled=True, automations_beat_enabled=True)


def _production_settings(**overrides):
    values = {
        "env": "production",
        "jwt_secret": "x" * 32,
        "gemini_api_key": "gemini-test",
        "supermemory_api_key": "supermemory-test",
        "hermes_sidecar_url": "https://hermes.example.test",
        "hermes_sidecar_token": "hermes-test",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_requires_supermemory():
    with pytest.raises(ValueError, match="SUPERMEMORY_API_KEY"):
        _production_settings(supermemory_api_key=None)


def test_production_requires_hermes_url_and_token():
    with pytest.raises(ValueError, match="HERMES_SIDECAR_URL"):
        _production_settings(hermes_sidecar_url=None)
    with pytest.raises(ValueError, match="HERMES_SIDECAR_TOKEN"):
        _production_settings(hermes_sidecar_token=None)


def test_production_accepts_core_memory_and_reasoning_services():
    settings = _production_settings()
    assert settings.supermemory_api_key == "supermemory-test"
    assert settings.hermes_sidecar_url == "https://hermes.example.test"
