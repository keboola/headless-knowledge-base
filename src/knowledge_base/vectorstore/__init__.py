"""Vector store module for embeddings and indexing.

Graphiti is now the source of truth for chunk storage.
This module provides embeddings and ChunkData for indexing.
"""


def __getattr__(name: str):
    """Lazy import for vectorstore components."""
    if name in ("BaseEmbeddings", "SentenceTransformerEmbeddings", "get_embeddings"):
        from knowledge_base.vectorstore.embeddings import (
            BaseEmbeddings,
            SentenceTransformerEmbeddings,
            get_embeddings,
        )
        return locals()[name]

    if name == "ChunkData":
        from knowledge_base.vectorstore.indexer import ChunkData
        return ChunkData

    # Backward compatibility: VectorIndexer now wraps GraphitiIndexer
    if name == "VectorIndexer":
        from knowledge_base.graph.graphiti_indexer import GraphitiIndexer
        return GraphitiIndexer

    # SearchResult is now in search.models
    if name == "SearchResult":
        from knowledge_base.search.models import SearchResult
        return SearchResult

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseEmbeddings",
    "SentenceTransformerEmbeddings",
    "get_embeddings",
    "ChunkData",
    "VectorIndexer",  # Alias for GraphitiIndexer
    "SearchResult",
]
