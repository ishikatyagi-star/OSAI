"""Local Ollama text generation — the egress-safe path for restricted tiers.

When the org's data-routing policy forbids sending a tier to cloud models
(llm/policy.py), synthesis runs here instead: same prompt, local model, no
external request. Raises on failure so callers can degrade honestly (withhold
restricted context from cloud synthesis) rather than silently leaking it.
"""

from __future__ import annotations

import httpx

from config import settings


async def generate_local(prompt: str, timeout: float = 60.0) -> str:
    """One-shot local chat completion via Ollama. Raises httpx errors /
    ValueError on any failure — never falls back to a cloud provider."""
    url = f"{settings.ollama_url}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
    if not content:
        raise ValueError("Ollama returned an empty response")
    return content
