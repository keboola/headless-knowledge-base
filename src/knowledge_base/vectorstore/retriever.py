"""Vector retriever for semantic search over indexed chunks."""

import logging
from dataclasses import dataclass
from typing import Any

from knowledge_base.vectorstore.client import ChromaClient
from knowledge_base.vectorstore.embeddings import BaseEmbeddings, get_embeddings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""

    chunk_id: str
    content: str
    score: float  # Similarity score (higher is better)
    metadata: dict[str, Any]

    @property
    def page_title(self) -> str:
        return self.metadata.get("page_title", "")

    @property
    def url(self) -> str:
        return self.metadata.get("url", "")

    @property
    def space_key(self) -> str:
        return self.metadata.get("space_key", "")

    @property
    def doc_type(self) -> str:
        return self.metadata.get("doc_type", "")

    @property
    def quality_score(self) -> float:
        """Quality score from ChromaDB metadata (source of truth)."""
        return self.metadata.get("quality_score", 100.0)

    @property
    def owner(self) -> str:
        """Document owner from ChromaDB metadata."""
        return self.metadata.get("owner", "")


class VectorRetriever:
    """Retrieves relevant chunks using vector similarity search."""

    def __init__(
        self,
        embeddings: BaseEmbeddings | None = None,
        chroma: ChromaClient | None = None,
    ):
        """Initialize the retriever.

        Args:
            embeddings: Embeddings provider (defaults to configured provider)
            chroma: ChromaDB client (defaults to new client)
        """
        self.embeddings = embeddings or get_embeddings()
        self.chroma = chroma or ChromaClient()

    async def search(
        self,
        query: str,
        n_results: int = 5,
        space_key: str | None = None,
        doc_type: str | None = None,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        """Search for relevant chunks.

        Args:
            query: Search query text
            n_results: Maximum number of results to return
            space_key: Optional filter by space key
            doc_type: Optional filter by document type
            min_score: Minimum similarity score (0-1, higher is more similar)

        Returns:
            List of search results ordered by relevance
        """
        # Generate query embedding
        query_embedding = await self.embeddings.embed_single(query)

        # Build filter
        where_filter = self._build_filter(space_key, doc_type)

        # Query ChromaDB
        results = await self.chroma.query(
            query_embedding=query_embedding,
            n_results=n_results,
            where=where_filter,
        )

        # Convert to SearchResult objects
        search_results = []
        if results and results.get("ids") and results["ids"][0]:
            ids = results["ids"][0]
            documents = results["documents"][0] if results.get("documents") else [""] * len(ids)
            metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)
            distances = results["distances"][0] if results.get("distances") else [1.0] * len(ids)

            for chunk_id, content, metadata, distance in zip(
                ids, documents, metadatas, distances
            ):
                # Convert distance to similarity score (cosine distance -> similarity)
                # ChromaDB returns L2 distance for cosine, where 0 = identical
                score = 1 - (distance / 2)  # Approximate conversion

                if score >= min_score:
                    search_results.append(
                        SearchResult(
                            chunk_id=chunk_id,
                            content=content,
                            score=score,
                            metadata=metadata,
                        )
                    )

        logger.debug(f"Search for '{query[:50]}...' returned {len(search_results)} results")
        return search_results

    def _build_filter(
        self,
        space_key: str | None = None,
        doc_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Build ChromaDB where filter.

        Args:
            space_key: Filter by space key
            doc_type: Filter by document type

        Returns:
            Filter dictionary or None
        """
        conditions = []

        if space_key:
            conditions.append({"space_key": {"$eq": space_key}})

        if doc_type:
            conditions.append({"doc_type": {"$eq": doc_type}})

        if not conditions:
            return None

        if len(conditions) == 1:
            return conditions[0]

        return {"$and": conditions}

    async def check_health(self) -> bool:
        """Check if the retriever is healthy.

        Returns:
            True if healthy, False otherwise
        """
        return await self.chroma.check_health()

    async def get_stats(self) -> dict[str, Any]:
        """Get retriever statistics.

        Returns:
            Statistics dictionary
        """
        count = await self.chroma.count()
        return {
            "indexed_chunks": count,
            "embedding_provider": self.embeddings.provider_name,
        }
