"""Schemas for the 'Ask OSAI' agent — mirror osai-web/lib/types.ts exactly."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from api.schemas.search import SourceCitation

ChatRole = Literal["user", "assistant"]
AgentActionStatus = Literal["proposed", "executed", "failed", "skipped"]
ArtifactTone = Literal["neutral", "success", "warning", "danger", "info"]
AskUiArtifactKind = Literal["answer_summary", "source_table", "action_plan", "context_gap"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(min_length=1, max_length=4_000)


class AskRequest(BaseModel):
    # org_id is resolved server-side from the caller's session (see the /ask
    # route); any client-supplied value is ignored to prevent cross-tenant access.
    org_id: str = ""
    question: str = Field(min_length=1, max_length=40_000)
    # Explicit composer intent biases action planning without changing the user's
    # question or bypassing the proposal/confirmation boundary.
    intent: Literal["ask", "action"] = "ask"
    conversation_id: str | None = None
    # Only the bounded recent window is accepted by the model/sidecar boundary.
    # This keeps one otherwise-rate-limited request from carrying an unbounded
    # conversation payload.
    history: list[ChatMessage] | None = Field(default=None, max_length=10)
    # Optional department scope for retrieval ("Ask Engineering").
    department_id: str | None = None
    # The trusted /ask route owns persisted exchanges. A request ID makes the
    # write idempotent; thread_id continues an existing visible thread, while a
    # missing thread_id creates one after the answer succeeds.
    thread_id: str | None = None
    request_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def normalize_non_blank_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must contain non-whitespace characters")
        return value


class AgentAction(BaseModel):
    id: str
    tool: str
    action: str
    summary: str
    status: AgentActionStatus
    requires_confirmation: bool
    params: dict[str, Any] | None = None
    external_url: str | None = None
    error: str | None = None


class AskUiArtifactMetric(BaseModel):
    label: str
    value: str
    tone: ArtifactTone | None = None


class AskUiArtifactRow(BaseModel):
    label: str
    value: str
    meta: str | None = None
    href: str | None = None
    confidence: float | None = None
    tone: ArtifactTone | None = None


class AskUiArtifact(BaseModel):
    id: str
    kind: AskUiArtifactKind
    title: str
    subtitle: str | None = None
    metrics: list[AskUiArtifactMetric] | None = None
    rows: list[AskUiArtifactRow] | None = None


class AskResponse(BaseModel):
    conversation_id: str
    answer: str = Field(min_length=1, max_length=40_000)
    citations: list[SourceCitation] = Field(default_factory=list)
    actions_taken: list[AgentAction] = Field(default_factory=list)
    enough_context: bool = False
    model_route: str | None = None
    latency_ms: int | None = None
    # Which reasoning engine produced the answer: the in-house RAG agent ("osai")
    # or the per-user Hermes sidecar ("hermes"). Lets the UI/evals assert Hermes
    # actually ran and surfaces silent fallbacks.
    via: Literal["osai", "hermes"] = "osai"
    ui_artifacts: list[AskUiArtifact] | None = None
    thread_id: str | None = None
    persistence_status: Literal["not_requested", "saved"] = "not_requested"


class ConfirmActionRequest(BaseModel):
    conversation_id: str


class ConfirmActionResult(BaseModel):
    id: str
    status: Literal["executed", "failed"]
    external_url: str | None = None
    message: str
    error: str | None = None


class DismissActionResult(BaseModel):
    id: str
    status: Literal["skipped", "failed"]
    message: str
    error: str | None = None
