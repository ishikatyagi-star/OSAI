"""Org knowledge-graph schemas — mirror osai-web/lib/types.ts GraphEntity/GraphEdge."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GraphEntityType = Literal[
    "person", "project", "decision", "source", "department", "ticket"
]
GraphEdgeType = Literal[
    "owns", "attended", "works_at", "references", "blocks", "decided"
]


class GraphEntity(BaseModel):
    id: str
    type: GraphEntityType
    label: str
    summary: str | None = None
    source_tool: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    degree: int = 0


class GraphEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    type: GraphEdgeType
    label: str
    confidence: float = 1.0
    source_tool: str | None = None
