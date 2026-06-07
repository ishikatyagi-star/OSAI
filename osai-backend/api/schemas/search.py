from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    org_id: str
    query: str
    requester_permissions: list[str] = Field(default_factory=list)


class SourceCitation(BaseModel):
    source_tool: str
    source_record_title: str
    url: str | None = None
    confidence: float = 0.0


class SearchResponse(BaseModel):
    answer: str
    citations: list[SourceCitation] = Field(default_factory=list)
    enough_context: bool
