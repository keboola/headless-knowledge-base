"""Search result models for the knowledge base.

This module provides a shared SearchResult class that can be imported
without ChromaDB dependencies.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class SearchResult:
    """A single search result from any search backend.

    This class is used by both GraphitiRetriever and HybridRetriever
    to provide a consistent interface for search results.
    """

    chunk_id: str
    content: str
    score: float  # Similarity/relevance score (higher is better)
    metadata: dict[str, Any]

    @property
    def page_title(self) -> str:
        """Document title from metadata."""
        return self.metadata.get("page_title", "")

    @property
    def page_id(self) -> str:
        """Document page ID from metadata."""
        return self.metadata.get("page_id", "")

    @property
    def url(self) -> str:
        """Document URL from metadata."""
        return self.metadata.get("url", "")

    @property
    def space_key(self) -> str:
        """Confluence space key from metadata."""
        return self.metadata.get("space_key", "")

    @property
    def doc_type(self) -> str:
        """Document type (policy, how-to, FAQ, etc.) from metadata."""
        return self.metadata.get("doc_type", "")

    @property
    def quality_score(self) -> float:
        """Quality score from metadata (0-100)."""
        return self.metadata.get("quality_score", 100.0)

    @property
    def owner(self) -> str:
        """Document owner from metadata."""
        return self.metadata.get("owner", "")

    @property
    def author(self) -> str:
        """Document author from metadata."""
        return self.metadata.get("author", "")

    @property
    def topics(self) -> list[str]:
        """Topics from metadata (JSON array stored as string)."""
        import json
        topics_str = self.metadata.get("topics", "[]")
        if isinstance(topics_str, list):
            return topics_str
        try:
            return json.loads(topics_str)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def chunk_index(self) -> int:
        """Chunk index within the document."""
        return self.metadata.get("chunk_index", 0)

    @property
    def classification(self) -> str:
        """Security classification (public, internal, confidential)."""
        return self.metadata.get("classification", "internal")
