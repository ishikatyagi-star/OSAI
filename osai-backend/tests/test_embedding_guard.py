"""A deployment must not silently serve hash embeddings.

Without OSAI_GEMINI_API_KEY the embedding provider falls back to 64-dim
deterministic hash vectors, which is keyword bucketing rather than semantic
retrieval. Ask keeps answering, just far worse, with nothing in the logs — so a
non-local deployment has to fail at boot instead.
"""

from __future__ import annotations

import pytest

from config import Settings

_STRONG_SECRET = "x" * 48


def _settings(**overrides):
    base = {"jwt_secret": _STRONG_SECRET, "gemini_api_key": "test-key"}
    return Settings(**{**base, **overrides})


@pytest.mark.parametrize("env", ["production", "staging"])
def test_non_local_refuses_to_boot_without_a_gemini_key(env):
    with pytest.raises(ValueError) as exc:
        _settings(env=env, gemini_api_key=None)
    message = str(exc.value)
    assert "OSAI_GEMINI_API_KEY" in message
    # The error has to say *why*, or the next person just sets it blindly.
    assert "hash" in message.lower()


@pytest.mark.parametrize("env", ["production", "staging"])
def test_non_local_boots_with_a_gemini_key(env):
    assert _settings(env=env).gemini_api_key == "test-key"


def test_local_keeps_the_hash_fallback():
    """Local dev must still run with no key, so the stack works offline."""
    cfg = _settings(
        env="local",
        gemini_api_key=None,
        jwt_secret="dev-only-insecure-secret-change-me",
    )
    assert cfg.gemini_api_key is None


def test_provider_selection_matches_the_key():
    """The guard only matters because this is what the key actually controls."""
    import config as config_module
    from memory.embeddings import (
        GeminiEmbeddingProvider,
        HashEmbeddingProvider,
        _build_default_provider,
    )

    original = config_module.settings.gemini_api_key
    try:
        config_module.settings.gemini_api_key = None
        assert isinstance(_build_default_provider(), HashEmbeddingProvider)
    finally:
        config_module.settings.gemini_api_key = original

    if original:
        assert isinstance(_build_default_provider(), GeminiEmbeddingProvider)
