"""Embedding providers. Falls back to deterministic hash embeddings if no Gemini key is set."""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING

from config import settings

if TYPE_CHECKING:
    pass


class EmbeddingProvider:
    dimension: int

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Hash-based dev embeddings (no external dependency, always available)
# ---------------------------------------------------------------------------


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic local embedding substitute for development and tests."""

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = [t for t in text.lower().split() if t]
        for token in tokens or [text.lower()]:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


# ---------------------------------------------------------------------------
# Gemini embedding provider (text-embedding-004, 768-dimensional)
# ---------------------------------------------------------------------------


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Production embeddings via Google Gemini (gemini-embedding-001)."""

    def __init__(
        self, api_key: str, model: str = "gemini-embedding-001", dimension: int = 768
    ) -> None:
        from google import genai  # type: ignore[import-untyped]

        self._client = genai.Client(api_key=api_key)
        self._model = model
        # gemini-embedding-001 returns 3072 dims by default; request the
        # collection dimension explicitly so vectors stay consistent.
        self.dimension = dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # Gemini embed_content is synchronous; run in batches of 100 (API limit).
        import asyncio

        from google.genai import types as genai_types  # type: ignore[import-untyped]
        from tenacity import AsyncRetrying, stop_after_attempt, wait_random_exponential

        loop = asyncio.get_event_loop()
        results: list[list[float]] = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # One transient Gemini/network failure otherwise fails the whole
            # sync's embedding pass; retry each batch a couple of times.
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_random_exponential(multiplier=0.5, max=4),
                reraise=True,
            ):
                with attempt:
                    response = await loop.run_in_executor(
                        None,
                        lambda b=batch: self._client.models.embed_content(
                            model=self._model,
                            contents=b,
                            config=genai_types.EmbedContentConfig(
                                task_type="RETRIEVAL_DOCUMENT",
                                output_dimensionality=self.dimension,
                            ),
                        ),
                    )
            for emb in response.embeddings:
                # Truncated (sub-3072) MRL embeddings are not unit-normalized;
                # normalize so cosine similarity in Qdrant is meaningful.
                values = list(emb.values)
                norm = math.sqrt(sum(v * v for v in values)) or 1.0
                results.append([v / norm for v in values])
        return results


# ---------------------------------------------------------------------------
# Voyage AI embedding provider — no-billing-required alternative to Gemini
# ---------------------------------------------------------------------------


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Embeddings via Voyage AI's REST API (Bearer auth). Batches of 128 (the
    API cap); each batch retried on transient failures."""

    # Dimensions voyage-3.x / voyage-3.5 models can emit via output_dimension.
    _SUPPORTED_DIMS = (256, 512, 1024, 2048)

    def __init__(
        self,
        api_key: str,
        model: str = "voyage-3.5-lite",
        dimension: int = 512,
        base_url: str = "https://api.voyageai.com/v1",
    ) -> None:
        if dimension not in self._SUPPORTED_DIMS:
            # Fail loudly at boot rather than 400 on every embed at runtime. The
            # Gemini default of 768 is not a valid Voyage dimension.
            raise ValueError(
                f"OSAI_EMBEDDING_DIMENSION={dimension} is not supported by Voyage "
                f"({model}); use one of {self._SUPPORTED_DIMS}. Switching from "
                "Gemini also requires recreating the Qdrant collection at the new "
                "dimension."
            )
        self._api_key = api_key
        self._model = model
        self.dimension = dimension
        self._base_url = base_url.rstrip("/")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import httpx
        from tenacity import AsyncRetrying, stop_after_attempt, wait_random_exponential

        results: list[list[float]] = []
        batch_size = 128
        async with httpx.AsyncClient(timeout=60) as client:
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                # Longer backoff than usual: Voyage free-tier limits are
                # per-minute, so a 429 needs a multi-second wait to clear, not a
                # sub-second retry.
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(4),
                    wait=wait_random_exponential(multiplier=1, max=30),
                    reraise=True,
                ):
                    with attempt:
                        resp = await client.post(
                            f"{self._base_url}/embeddings",
                            headers={"Authorization": f"Bearer {self._api_key}"},
                            json={
                                "input": batch,
                                "model": self._model,
                                "input_type": "document",
                                "output_dimension": self.dimension,
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()
                # Voyage returns embeddings already L2-normalized; keep as-is.
                for item in sorted(data["data"], key=lambda d: d["index"]):
                    results.append(list(item["embedding"]))
        return results


# ---------------------------------------------------------------------------
# Default provider — Voyage, then Gemini, then hash fallback
# ---------------------------------------------------------------------------


def _build_default_provider() -> EmbeddingProvider:
    # Voyage first: it's the no-billing-required path, so when a key is present
    # it's the deliberate choice over Gemini.
    if settings.voyage_api_key:
        return VoyageEmbeddingProvider(
            api_key=settings.voyage_api_key,
            model=settings.voyage_model,
            dimension=settings.embedding_dimension,
            base_url=settings.voyage_base_url,
        )
    if settings.gemini_api_key:
        return GeminiEmbeddingProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_embedding_model,
            dimension=settings.embedding_dimension,
        )
    return HashEmbeddingProvider(dimension=settings.embedding_dimension)


default_embedding_provider: EmbeddingProvider = _build_default_provider()
