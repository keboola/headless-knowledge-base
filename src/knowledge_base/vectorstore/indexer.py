"""Chunk data structures for knowledge indexing.

Graphiti is now the SOURCE OF TRUTH for all knowledge data.
This module provides the ChunkData dataclass for chunk indexing.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChunkData:
    """Data structure for a chunk to be indexed.

    All fields are stored as metadata for search filtering.
    """

    # Required fields
    chunk_id: str
    content: str
    page_id: str
    page_title: str
    chunk_index: int

    # Source info
    space_key: str = ""
    url: str = ""
    author: str = ""
    created_at: str = ""  # ISO datetime
    updated_at: str = ""  # ISO datetime

    # Chunk structure
    chunk_type: str = "text"  # text, code, table, list
    parent_headers: str = "[]"  # JSON array

    # Quality
    quality_score: float = 100.0  # 0-100
    access_count: int = 0
    feedback_count: int = 0

    # Governance
    owner: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""
    classification: str = "internal"  # public, internal, confidential

    # AI metadata
    doc_type: str = ""  # policy, how-to, reference, FAQ, quick_fact
    topics: str = "[]"  # JSON array
    audience: str = "[]"  # JSON array
    complexity: str = ""  # beginner, intermediate, advanced
    summary: str = ""

    def to_metadata(self) -> dict[str, Any]:
        """Convert to metadata dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "page_id": self.page_id,
            "page_title": self.page_title,
            "chunk_type": self.chunk_type,
            "chunk_index": self.chunk_index,
            "space_key": self.space_key,
            "url": self.url,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "parent_headers": self.parent_headers,
            "quality_score": self.quality_score,
            "access_count": self.access_count,
            "feedback_count": self.feedback_count,
            "owner": self.owner,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "classification": self.classification,
            "doc_type": self.doc_type,
            "topics": self.topics,
            "audience": self.audience,
            "complexity": self.complexity,
            "summary": self.summary[:500] if self.summary else "",
        }
