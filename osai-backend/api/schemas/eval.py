"""Eval schemas — mirror osai-web/lib/types.ts EvalRun/EvalCase."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EvalCategory = Literal["ticket_triage", "ownership", "routing", "qa"]


class EvalCase(BaseModel):
    id: str
    category: EvalCategory
    question: str
    expected: str
    actual: str
    passed: bool
    score: float
    latency_ms: int
    notes: str | None = None


class EvalRun(BaseModel):
    run_id: str
    created_at: str
    model_route: str
    pass_rate: float
    total: int
    passed: int
    failed: int
    cases: list[EvalCase] = Field(default_factory=list)
