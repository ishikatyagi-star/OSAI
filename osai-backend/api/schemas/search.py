from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    # org_id / requester_permissions / requester_tier are resolved server-side from
    # the caller's session (see the /search route); client-supplied values ignored.
    org_id: str = ""
    query: str
    requester_permissions: list[str] = Field(default_factory=list)
    # Caller's data-clearance tier; "red" = see-all (admin/system/demo default).
    requester_tier: str = "red"


class SourceCitation(BaseModel):
    source_tool: str
    source_record_title: str
    url: str | None = None
    confidence: float = 0.0


class SearchResponse(BaseModel):
    answer: str
    citations: list[SourceCitation] = Field(default_factory=list)
    enough_context: bool
