"""Vector store module for embeddings and ChromaDB operations.

This module provides lazy imports to avoid loading heavy dependencies
(chromadb, sentence-transformers) until they're actually needed.
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

    if name == "ChromaClient":
        from knowledge_base.vectorstore.client import ChromaClient
        return ChromaClient

    if name == "VectorIndexer":
        from knowledge_base.vectorstore.indexer import VectorIndexer
        return VectorIndexer

    if name == "ChunkData":
        from knowledge_base.vectorstore.indexer import ChunkData
        return ChunkData

    if name in ("VectorRetriever", "SearchResult"):
        from knowledge_base.vectorstore.retriever import VectorRetriever, SearchResult
        return locals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseEmbeddings",
    "SentenceTransformerEmbeddings",
    "get_embeddings",
    "ChromaClient",
    "VectorIndexer",
    "ChunkData",
    "VectorRetriever",
    "SearchResult",
]
