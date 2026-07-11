from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    # org_id / requester_permissions / requester_tier are resolved server-side from
    # the caller's session (see the /search route); client-supplied values ignored.
    org_id: str = ""
    query: str
    requester_permissions: list[str] = Field(default_factory=list)
    # Caller's data-clearance tier; "red" = see-all (admin/system/demo default).
    requester_tier: str = "red"
    # Caller's user id — scopes org-memory recall (private memories stay private).
    # None = system context (see-all), same stance as the other requester fields.
    requester_user_id: str | None = None
    # Optional department scope: restrict retrieval to documents attributed to
    # this department ("Ask Engineering"). None = whole org corpus.
    department_id: str | None = None


class SourceCitation(BaseModel):
    source_tool: str
    source_record_title: str
    url: str | None = None
    confidence: float = 0.0
    # Tier of the cited document, so downstream egress points (e.g. the Hermes
    # sidecar context builder) can apply the org's data-routing policy.
    data_tier: str | None = None
    # Policy explain: why this source is visible to the requester, and where its
    # content was allowed to go. Derived from the same checks that made the
    # decision (_visible / cloud_llm_allowed), so it can't drift from reality.
    access_reason: str | None = None
    model_routing: str | None = None  # "cloud" | "local-only"
    routing_reason: str | None = None


class SearchResponse(BaseModel):
    answer: str
    citations: list[SourceCitation] = Field(default_factory=list)
    enough_context: bool
