"""Schemas for the 'Ask OSAI' agent — mirror osai-web/lib/types.ts exactly."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from api.schemas.search import SourceCitation

ChatRole = Literal["user", "assistant"]
AgentActionStatus = Literal["proposed", "executed", "failed", "skipped"]
ArtifactTone = Literal["neutral", "success", "warning", "danger", "info"]
AskUiArtifactKind = Literal[
    "answer_summary", "source_table", "action_plan", "context_gap"
]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str


class AskRequest(BaseModel):
    # org_id is resolved server-side from the caller's session (see the /ask
    # route); any client-supplied value is ignored to prevent cross-tenant access.
    org_id: str = ""
    question: str
    conversation_id: str | None = None
    history: list[ChatMessage] | None = None


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
    answer: str
    citations: list[SourceCitation] = Field(default_factory=list)
    actions_taken: list[AgentAction] = Field(default_factory=list)
    enough_context: bool = False
    model_route: str | None = None
    latency_ms: int | None = None
    ui_artifacts: list[AskUiArtifact] | None = None


class ConfirmActionRequest(BaseModel):
    conversation_id: str


class ConfirmActionResult(BaseModel):
    id: str
    status: Literal["executed", "failed"]
    external_url: str | None = None
    message: str
    error: str | None = None
