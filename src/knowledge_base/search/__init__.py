"""Hybrid search module using Graphiti's unified search.

Graphiti provides built-in hybrid search combining:
- Semantic similarity (embeddings)
- BM25 keyword matching
- Graph relationships
"""

from knowledge_base.search.hybrid import HybridRetriever
from knowledge_base.search.models import SearchResult

__all__ = ["HybridRetriever", "SearchResult"]
