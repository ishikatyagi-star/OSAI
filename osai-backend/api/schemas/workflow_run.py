from typing import Literal

from pydantic import BaseModel, Field

from api.schemas.connector import DataTier


class ActionItem(BaseModel):
    title: str
    owner: str | None = None
    due_date: str | None = None
    destination: Literal["notion", "freshdesk", "slack", "manual"] = "manual"
    source_quote: str | None = None
    confidence: float = Field(ge=0, le=1, default=0.0)


class WorkflowRunCreate(BaseModel):
    org_id: str
    input_text: str
    destination: Literal["notion", "freshdesk", "slack", "manual"] = "manual"
    data_tier: DataTier = "normal"


class WorkflowRunResponse(BaseModel):
    id: str
    status: Literal["succeeded", "failed", "needs_review"]
    model_route: str
    action_items: list[ActionItem] = Field(default_factory=list)
    audit_event_ids: list[str] = Field(default_factory=list)
