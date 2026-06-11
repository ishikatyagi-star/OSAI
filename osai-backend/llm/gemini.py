"""LLM text-generation entrypoint.

Provider-aware: routes to OpenRouter (OpenAI-compatible) when an OpenRouter key
is configured, otherwise Gemini. Embeddings remain Gemini-only (see
memory/embeddings.py). Call sites import `generate` / `generate_json` from here.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from config import settings


def _get_client():
    from google import genai  # type: ignore[import-untyped]

    if not settings.gemini_api_key:
        raise RuntimeError("OSAI_GEMINI_API_KEY is not set.")
    return genai.Client(api_key=settings.gemini_api_key)


async def generate(prompt: str, model: str | None = None) -> str:
    """Run a single-turn prompt and return the text response."""
    if settings.openrouter_api_key:
        return await _openrouter_generate(prompt, model)
    return await _gemini_generate(prompt, model)


async def _gemini_generate(prompt: str, model: str | None = None) -> str:
    client = _get_client()
    _model = model or settings.gemini_model
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(model=_model, contents=prompt),
    )
    return response.text.strip()


async def _openrouter_generate(prompt: str, model: str | None = None) -> str:
    _model = model or settings.openrouter_model
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            json={"model": _model, "messages": [{"role": "user", "content": prompt}]},
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


async def generate_json(prompt: str, model: str | None = None) -> Any:
    """Run a prompt expecting JSON output and parse it."""
    import json
    import re

    raw = await generate(prompt, model=model)
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    return json.loads(cleaned)
