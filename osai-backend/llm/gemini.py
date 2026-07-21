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
    if settings.llm_api_key:
        return await _openai_compatible_generate(prompt, model)
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


async def _openai_compatible_generate(prompt: str, model: str | None = None) -> str:
    _model = model or settings.llm_model
    payload = {"model": _model, "messages": [{"role": "user", "content": prompt}]}
    # Free-tier providers (e.g. Groq) rate-limit under load; a single 429 or 5xx
    # otherwise fails the whole answer ("couldn't generate a summary"). Retry a
    # few times with backoff, honouring Retry-After when present.
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(3):
            resp = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json=payload,
            )
            if resp.status_code in (429, 500, 502, 503, 529):
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if retry_after else 1.5 * (attempt + 1)
                last_exc = httpx.HTTPStatusError(
                    f"LLM {resp.status_code}", request=resp.request, response=resp
                )
                if attempt < 2:
                    await asyncio.sleep(min(delay, 8))
                    continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    raise last_exc or RuntimeError("LLM generation failed")


def tool_calling_available() -> bool:
    """Function-calling needs an OpenAI-compatible provider (Groq/OpenRouter);
    the Gemini text path here doesn't expose it."""
    return bool(settings.llm_api_key)


async def chat_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """One OpenAI-compatible chat turn with function-calling. Returns the raw
    assistant message dict, which may contain `tool_calls`. The caller runs the
    loop (execute tools, append results, call again). Provider-agnostic: any
    tool-calling OpenAI-compatible endpoint works, so no per-connector code is
    needed — the model chooses tools from their schemas."""
    _model = model or settings.llm_model
    payload: dict[str, Any] = {"model": _model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(3):
            resp = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json=payload,
            )
            if resp.status_code in (429, 500, 502, 503, 529):
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if retry_after else 1.5 * (attempt + 1)
                last_exc = httpx.HTTPStatusError(
                    f"LLM {resp.status_code}", request=resp.request, response=resp
                )
                if attempt < 2:
                    await asyncio.sleep(min(delay, 8))
                    continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]
    raise last_exc or RuntimeError("LLM tool-calling failed")


async def generate_json(prompt: str, model: str | None = None) -> Any:
    """Run a prompt expecting JSON output and parse it."""
    import json
    import re

    raw = await generate(prompt, model=model)
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    return json.loads(cleaned)
