"""Pydantic schemas for metadata."""

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Schema for document metadata extracted by LLM."""

    topics: list[str] = Field(default_factory=list, description="3-5 main topics")
    intents: list[str] = Field(
        default_factory=list, description="2-3 use cases when this document is useful"
    )
    audience: list[str] = Field(
        default_factory=list, description="Who should read this document"
    )
    doc_type: str = Field(
        default="general",
        description="Document type: policy, how-to, reference, FAQ, announcement, meeting-notes",
    )
    key_entities: list[str] = Field(
        default_factory=list,
        description="Products, services, tools, and locations mentioned",
    )
    summary: str = Field(default="", description="1-2 sentence summary")
    complexity: str = Field(
        default="intermediate",
        description="Complexity level: beginner, intermediate, advanced",
    )

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentMetadata":
        """Create from a dictionary, handling missing or invalid fields."""
        return cls(
            topics=data.get("topics", []) if isinstance(data.get("topics"), list) else [],
            intents=data.get("intents", []) if isinstance(data.get("intents"), list) else [],
            audience=data.get("audience", []) if isinstance(data.get("audience"), list) else [],
            doc_type=data.get("doc_type", "general") if isinstance(data.get("doc_type"), str) else "general",
            key_entities=data.get("key_entities", []) if isinstance(data.get("key_entities"), list) else [],
            summary=data.get("summary", "") if isinstance(data.get("summary"), str) else "",
            complexity=data.get("complexity", "intermediate") if isinstance(data.get("complexity"), str) else "intermediate",
        )
