"""Hybrid retriever using Graphiti's built-in BM25 + vector + graph search.

Graphiti provides a unified hybrid search that combines:
- Semantic similarity (embeddings)
- BM25 keyword matching
- Graph relationships

This simplifies the architecture by eliminating:
- Separate BM25 index file
- ChromaDB dependency
- RRF fusion logic

Quality score boosting is still applied post-search.
"""

import logging
from typing import Any

from knowledge_base.config import settings

logger = logging.getLogger(__name__)

# Quality boost weight - how much quality affects ranking (0.2 = ±20% adjustment)
QUALITY_BOOST_WEIGHT = 0.2


class HybridRetriever:
    """Hybrid retriever using Graphiti's unified search.

    Provides the same interface as the previous BM25+Vector implementation
    but delegates to GraphitiRetriever for all search operations.
    """

    def __init__(self):
        """Initialize hybrid retriever.

        Uses GraphitiRetriever as the sole search backend.
        """
        self._retriever = None

    def _get_retriever(self):
        """Get GraphitiRetriever lazily to avoid circular imports."""
        if self._retriever is None:
            from knowledge_base.graph.graphiti_retriever import get_graphiti_retriever
            self._retriever = get_graphiti_retriever()
        return self._retriever

    async def search(
        self,
        query: str,
        k: int | None = None,
        bm25_weight: float | None = None,  # Kept for API compatibility, ignored
        vector_weight: float | None = None,  # Kept for API compatibility, ignored
        space_key: str | None = None,
        doc_type: str | None = None,
        apply_quality_boost: bool = True,
        use_graph_expansion: bool | None = None,  # Kept for API compatibility, ignored (always uses graph)
    ):
        """Search using Graphiti's hybrid search.

        Args:
            query: Search query text
            k: Number of results to return (defaults to config)
            bm25_weight: DEPRECATED - Graphiti handles weights internally
            vector_weight: DEPRECATED - Graphiti handles weights internally
            space_key: Optional filter by Confluence space
            doc_type: Optional filter by document type
            apply_quality_boost: Whether to apply quality score boosting
            use_graph_expansion: DEPRECATED - Graphiti always uses graph

        Returns:
            List of SearchResult objects, ranked by combined score
        """
        from knowledge_base.graph.graphiti_retriever import SearchResult

        k = k or settings.SEARCH_TOP_K
        retriever = self._get_retriever()

        if not retriever.is_enabled:
            logger.error("Graphiti is DISABLED — check GRAPH_ENABLE_GRAPHITI setting. Returning empty results.")
            return []

        try:
            if apply_quality_boost:
                results = await retriever.search_with_quality_boost(
                    query=query,
                    num_results=k,
                    quality_boost_weight=QUALITY_BOOST_WEIGHT,
                    space_key=space_key,
                    doc_type=doc_type,
                )
            else:
                results = await retriever.search_chunks(
                    query=query,
                    num_results=k,
                    space_key=space_key,
                    doc_type=doc_type,
                )

            logger.debug(f"Hybrid search returned {len(results)} results for: {query[:50]}...")
            return results

        except Exception as e:
            logger.error(f"Hybrid search FAILED (returning 0 results): {e}", exc_info=True)
            return []

    async def search_bm25_only(
        self, query: str, k: int | None = None
    ):
        """Search using Graphiti (BM25 is included in hybrid).

        DEPRECATED: Graphiti doesn't support BM25-only search.
        This method now returns the same as regular search.
        """
        logger.warning("search_bm25_only is deprecated, using hybrid search instead")
        return await self.search(query, k=k, apply_quality_boost=False)

    async def search_vector_only(
        self,
        query: str,
        k: int | None = None,
        space_key: str | None = None,
        doc_type: str | None = None,
    ):
        """Search using Graphiti (vector is included in hybrid).

        DEPRECATED: Graphiti doesn't support vector-only search.
        This method now returns the same as regular search.
        """
        logger.warning("search_vector_only is deprecated, using hybrid search instead")
        return await self.search(
            query, k=k, space_key=space_key, doc_type=doc_type, apply_quality_boost=False
        )

    async def check_health(self) -> dict[str, Any]:
        """Check health of the search system."""
        retriever = self._get_retriever()

        try:
            # Check if Graphiti client is healthy
            graphiti_healthy = await retriever.client.check_health()
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            graphiti_healthy = False

        return {
            "graphiti_enabled": retriever.is_enabled,
            "graphiti_healthy": graphiti_healthy,
            "backend": settings.GRAPH_BACKEND,
        }
