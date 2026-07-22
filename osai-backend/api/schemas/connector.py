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


class AuthStatus(BaseModel):
    connector_key: str
    connected: bool
    scopes: list[str] = Field(default_factory=list)
    error: str | None = None


class SyncResult(BaseModel):
    connector_key: str
    status: Literal["succeeded", "failed", "partial"]
    cursor: str | None = None
    documents: list[SourceDocument] = Field(default_factory=list)
    error: str | None = None


class PermissionSet(BaseModel):
    principals: list[str] = Field(default_factory=list)
    public: bool = False


class ConnectorAction(BaseModel):
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    data_tier: DataTier = "normal"
    # Stable across safe retries; providers that support deduplication consume it.
    idempotency_key: str | None = None


class ActionResult(BaseModel):
    connector_key: str
    status: Literal["succeeded", "failed", "skipped"]
    external_id: str | None = None
    url: str | None = None
    error: str | None = None


class HealthcheckResult(BaseModel):
    connector_key: str
    healthy: bool
    message: str | None = None
