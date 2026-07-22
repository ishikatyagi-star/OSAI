from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.schemas.connector import DataTier


class ActionItem(BaseModel):
    title: str
    owner: str | None = None
    due_date: str | None = None
    destination: Literal["notion", "freshdesk", "slack", "manual"] = "manual"
    source_quote: str | None = None
    confidence: float = Field(ge=0, le=1, default=0.0)


class WorkflowRunCreate(BaseModel):
    # Resolved server-side from the caller's session; any body value is ignored.
    org_id: str = ""
    # Long enough for realistic meeting transcripts while bounding one LLM request.
    input_text: str = Field(min_length=1, max_length=100_000, strict=True)
    destination: Literal["notion", "freshdesk", "slack", "manual"] = "manual"
    data_tier: DataTier = "normal"

    @field_validator("input_text")
    @classmethod
    def reject_blank_input(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("input_text must contain non-whitespace characters")
        return value


class WorkflowRunResponse(BaseModel):
    id: str
    status: Literal["succeeded", "failed", "needs_review"]
    model_route: str
    action_items: list[ActionItem] = Field(default_factory=list)
    audit_event_ids: list[str] = Field(default_factory=list)
