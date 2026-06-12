"""Run the eval fixtures against the live retrieval/answer pipeline.

Scores each case by keyword coverage of the produced answer. Deterministic
without a live LLM (the retriever's mock fallback still returns grounded text).
Phase 6 / Hermes will optimize prompts against this same harness.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4

from api.schemas.eval import EvalCase, EvalRun
from api.schemas.search import SearchRequest
from config import settings
from evals.fixtures import FIXTURES
from memory.retriever import retrieve_answer

PASS_THRESHOLD = 0.5


def _model_route() -> str:
    if settings.llm_api_key:
        return f"llm:{settings.llm_model}"
    if settings.gemini_api_key:
        return f"gemini:{settings.gemini_model}"
    return "mock-fallback"


async def run_evals(org_id: str) -> EvalRun:
    cases: list[EvalCase] = []
    for fx in FIXTURES:
        started = time.monotonic()
        result = await retrieve_answer(
            SearchRequest(org_id=org_id, query=fx["question"])
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        actual = result.answer or ""
        lowered = actual.lower()
        matched = [kw for kw in fx["expected"] if kw.lower() in lowered]
        score = round(len(matched) / max(len(fx["expected"]), 1), 3)
        passed = score >= PASS_THRESHOLD
        cases.append(
            EvalCase(
                id=fx["id"],
                category=fx["category"],
                question=fx["question"],
                expected=" / ".join(fx["expected"]),
                actual=actual[:600],
                passed=passed,
                score=score,
                latency_ms=latency_ms,
                notes=f"matched {len(matched)}/{len(fx['expected'])} keywords",
            )
        )

    passed_n = sum(1 for c in cases if c.passed)
    total = len(cases)
    return EvalRun(
        run_id=str(uuid4()),
        created_at=datetime.now(UTC).isoformat(),
        model_route=_model_route(),
        pass_rate=round(passed_n / total, 3) if total else 0.0,
        total=total,
        passed=passed_n,
        failed=total - passed_n,
        cases=cases,
    )
