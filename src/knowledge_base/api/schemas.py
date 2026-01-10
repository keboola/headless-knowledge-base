"""API request and response schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Search request schema."""

    query: str = Field(..., description="Search query text", min_length=1)
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results to return")
    filters: dict[str, Any] | None = Field(
        default=None,
        description="Metadata filters (space_key, doc_type, topics, updated_after)",
    )
    include_content: bool = Field(
        default=True, description="Include chunk content in results"
    )
    search_method: Literal["hybrid", "vector", "bm25"] = Field(
        default="hybrid", description="Search method to use"
    )

    model_config = {"json_schema_extra": {
        "example": {
            "query": "How do I request PTO?",
            "top_k": 5,
            "filters": {"space_key": "HR"},
            "search_method": "hybrid",
        }
    }}


class SearchResultItem(BaseModel):
    """Individual search result."""

    chunk_id: str = Field(..., description="Unique chunk identifier")
    page_id: str = Field(default="", description="Confluence page ID")
    page_title: str = Field(default="", description="Page title")
    content: str | None = Field(default=None, description="Chunk content (if requested)")
    score: float = Field(..., description="Relevance score")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    url: str = Field(default="", description="Confluence page URL")

    model_config = {"json_schema_extra": {
        "example": {
            "chunk_id": "abc123",
            "page_id": "12345",
            "page_title": "PTO Policy",
            "content": "To request PTO, submit a request...",
            "score": 0.92,
            "metadata": {"space_key": "HR", "doc_type": "policy"},
            "url": "https://company.atlassian.net/wiki/spaces/HR/pages/12345",
        }
    }}


class SearchResponse(BaseModel):
    """Search response schema."""

    query: str = Field(..., description="Original search query")
    results: list[SearchResultItem] = Field(
        default_factory=list, description="Search results"
    )
    total_found: int = Field(..., description="Total number of results found")
    search_method: str = Field(..., description="Search method used")
    took_ms: int = Field(..., description="Search duration in milliseconds")

    model_config = {"json_schema_extra": {
        "example": {
            "query": "How do I request PTO?",
            "results": [],
            "total_found": 5,
            "search_method": "hybrid",
            "took_ms": 125,
        }
    }}


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="healthy", description="Service status")
    version: str = Field(default="0.1.0", description="API version")
    components: dict[str, Any] = Field(
        default_factory=dict, description="Component health status"
    )
