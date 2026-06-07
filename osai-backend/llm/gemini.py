"""Gemini client wrapper — reusable across LLM calls."""

from __future__ import annotations

import asyncio
from typing import Any

from config import settings


def _get_client():
    from google import genai  # type: ignore[import-untyped]

    if not settings.gemini_api_key:
        raise RuntimeError("OSAI_GEMINI_API_KEY is not set.")
    return genai.Client(api_key=settings.gemini_api_key)


async def generate(prompt: str, model: str | None = None) -> str:
    """Run a single-turn prompt and return the text response."""
    client = _get_client()
    _model = model or settings.gemini_model
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(model=_model, contents=prompt),
    )
    return response.text.strip()


async def generate_json(prompt: str, model: str | None = None) -> Any:
    """Run a prompt expecting JSON output and parse it."""
    import json
    import re

    raw = await generate(prompt, model=model)
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    return json.loads(cleaned)
