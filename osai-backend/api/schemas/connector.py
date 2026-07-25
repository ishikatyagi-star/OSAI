from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DataTier = Literal["normal", "amber", "red"]


class SourceDocument(BaseModel):
    source_id: str
    source_type: str
    org_id: str
    external_id: str
    title: str
    url: str | None = None
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    data_tier: DataTier = "normal"
    # Owning department (org-defined), for "Ask Engineering"-style scoping.
    department_id: str | None = None
