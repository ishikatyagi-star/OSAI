"""Smoke test for the gbrain client. Skips unless a local brain is initialized."""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.gbrain_client import GbrainClient

_BRAIN_HOME = "/tmp/osai-brain"


def _client_or_skip() -> GbrainClient:
    client = GbrainClient(home=_BRAIN_HOME)
    if not client.available() or not Path(_BRAIN_HOME, ".gbrain").exists():
        pytest.skip("gbrain not available (needs bun + an initialized brain home)")
    return client


def test_gbrain_put_get_roundtrip():
    client = _client_or_skip()
    assert client.put_page(
        "test/osai-smoke", "# OSAI Smoke\nOwned by [[people/anish]]."
    )
    page = client.get_page("test/osai-smoke")
    assert page is not None and "OSAI Smoke" in page


def test_gbrain_keyword_search():
    client = _client_or_skip()
    client.put_page("test/webhook-note", "# Webhook note\nAbout the zoom webhook.")
    results = client.search("webhook", limit=5)
    assert isinstance(results, list)
