"""LLM provider routing: OpenRouter preferred when configured, else Gemini."""

from __future__ import annotations

import llm.gemini as llm


async def test_routes_to_openrouter_when_key_set(monkeypatch):
    calls = {}

    async def fake_openrouter(prompt, model=None):
        calls["openrouter"] = (prompt, model)
        return "from-openrouter"

    async def fake_gemini(prompt, model=None):
        calls["gemini"] = True
        return "from-gemini"

    monkeypatch.setattr(llm.settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(llm, "_openrouter_generate", fake_openrouter)
    monkeypatch.setattr(llm, "_gemini_generate", fake_gemini)

    result = await llm.generate("hello")
    assert result == "from-openrouter"
    assert "gemini" not in calls


async def test_routes_to_gemini_when_no_openrouter_key(monkeypatch):
    async def fake_gemini(prompt, model=None):
        return "from-gemini"

    monkeypatch.setattr(llm.settings, "openrouter_api_key", None)
    monkeypatch.setattr(llm, "_gemini_generate", fake_gemini)

    result = await llm.generate("hello")
    assert result == "from-gemini"
