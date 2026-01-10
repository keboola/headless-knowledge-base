"""Hybrid retriever combining BM25 and vector search."""

import logging
from typing import Any

from knowledge_base.config import settings
from knowledge_base.search.bm25 import BM25Index
from knowledge_base.search.fusion import reciprocal_rank_fusion
from knowledge_base.vectorstore.client import ChromaClient
from knowledge_base.vectorstore.embeddings import BaseEmbeddings, get_embeddings
from knowledge_base.vectorstore.retriever import SearchResult

logger = logging.getLogger(__name__)

# Quality boost weight - how much quality affects ranking (0.2 = ±20% adjustment)
QUALITY_BOOST_WEIGHT = 0.2


class HybridRetriever:
    """Combines BM25 keyword search with vector semantic search.

    Uses Reciprocal Rank Fusion (RRF) to merge results from both methods.
    This provides better retrieval for:
    - Abbreviations and exact terms (BM25 strength)
    - Conceptual/semantic queries (Vector strength)
    """

    def __init__(
        self,
        bm25_index: BM25Index | None = None,
        embeddings: BaseEmbeddings | None = None,
        chroma: ChromaClient | None = None,
        bm25_weight: float | None = None,
        vector_weight: float | None = None,
    ):
        """Initialize hybrid retriever.

        Args:
            bm25_index: BM25 index (will be loaded from disk if None)
            embeddings: Embeddings provider (defaults to configured)
            chroma: ChromaDB client (defaults to new client)
            bm25_weight: Weight for BM25 results (defaults to config)
            vector_weight: Weight for vector results (defaults to config)
        """
        self.bm25 = bm25_index or BM25Index()
        self.embeddings = embeddings or get_embeddings()
        self.chroma = chroma or ChromaClient()

        self.bm25_weight = bm25_weight or settings.SEARCH_BM25_WEIGHT
        self.vector_weight = vector_weight or settings.SEARCH_VECTOR_WEIGHT

        # Try to load BM25 index if not provided
        if bm25_index is None:
            self.bm25.load()

    async def search(
        self,
        query: str,
        k: int | None = None,
        bm25_weight: float | None = None,
        vector_weight: float | None = None,
        space_key: str | None = None,
        doc_type: str | None = None,
        apply_quality_boost: bool = True,
    ) -> list[SearchResult]:
        """Search using both BM25 and vector methods.

        Args:
            query: Search query text
            k: Number of results to return (defaults to config)
            bm25_weight: Override BM25 weight for this search
            vector_weight: Override vector weight for this search
            space_key: Optional filter by Confluence space
            doc_type: Optional filter by document type
            apply_quality_boost: Whether to apply quality score boosting (Phase 11)

        Returns:
            List of SearchResult objects, ranked by combined score
        """
        k = k or settings.SEARCH_TOP_K
        bm25_w = bm25_weight or self.bm25_weight
        vector_w = vector_weight or self.vector_weight

        # Get more results from each method for better fusion
        fetch_k = k * 3

        # Run both searches
        bm25_results = self._search_bm25(query, k=fetch_k)
        vector_results = await self._search_vector(
            query, k=fetch_k, space_key=space_key, doc_type=doc_type
        )

        logger.debug(
            f"BM25 returned {len(bm25_results)} results, "
            f"Vector returned {len(vector_results)} results"
        )

        # If one method returns nothing, use the other
        if not bm25_results and not vector_results:
            return []

        if not bm25_results:
            results = vector_results[:k]
        elif not vector_results:
            # Convert BM25 results to SearchResult
            results = self._bm25_to_search_results(bm25_results[:k])
        else:
            # Fuse results using RRF
            bm25_ids = [(chunk_id, score) for chunk_id, score in bm25_results]
            vector_ids = [(r.chunk_id, r.score) for r in vector_results]

            fused = reciprocal_rank_fusion(
                bm25_ids,
                vector_ids,
                weights=(bm25_w, vector_w),
            )

            # Build final results with content and metadata
            results = self._build_results(fused[:k], bm25_results, vector_results)

        # Apply quality score boosting (Phase 11)
        if apply_quality_boost and results:
            results = await self._apply_quality_boost(results)

        return results

    async def _apply_quality_boost(self, results: list[SearchResult]) -> list[SearchResult]:
        """Apply quality score boosting to search results.

        Quality scores are read from ChromaDB metadata (source of truth).
        Per docs/ARCHITECTURE.md, ChromaDB is the single source of truth for quality scores.
        """
        try:
            from knowledge_base.lifecycle.scorer import apply_quality_boost

            # Get quality scores from ChromaDB metadata (source of truth)
            quality_scores = {}
            missing_count = 0

            for result in results:
                metadata = result.metadata or {}
                if "quality_score" in metadata:
                    # Normalize: ChromaDB stores 0-100, we need 0-1
                    raw_score = metadata["quality_score"]
                    quality_scores[result.chunk_id] = raw_score / 100.0
                else:
                    # Use default score for chunks without quality metadata
                    quality_scores[result.chunk_id] = 1.0  # Default to 100%
                    missing_count += 1

            if quality_scores:
                results = apply_quality_boost(
                    results, quality_scores, boost_weight=QUALITY_BOOST_WEIGHT
                )
                if missing_count > 0:
                    logger.debug(
                        f"Applied quality boost to {len(results)} results "
                        f"({missing_count} used default score)"
                    )

        except Exception as e:
            logger.warning(f"Quality boost failed, using original ranking: {e}")

        return results

    async def search_bm25_only(
        self, query: str, k: int | None = None
    ) -> list[SearchResult]:
        """Search using only BM25 (for testing/comparison)."""
        k = k or settings.SEARCH_TOP_K
        bm25_results = self._search_bm25(query, k=k)
        return self._bm25_to_search_results(bm25_results)

    async def search_vector_only(
        self,
        query: str,
        k: int | None = None,
        space_key: str | None = None,
        doc_type: str | None = None,
    ) -> list[SearchResult]:
        """Search using only vector (for testing/comparison)."""
        k = k or settings.SEARCH_TOP_K
        return await self._search_vector(query, k=k, space_key=space_key, doc_type=doc_type)

    def _search_bm25(self, query: str, k: int) -> list[tuple[str, float]]:
        """Run BM25 search."""
        if not self.bm25.is_built:
            logger.warning("BM25 index not built, skipping keyword search")
            return []

        return self.bm25.search(query, k=k)

    async def _search_vector(
        self,
        query: str,
        k: int,
        space_key: str | None = None,
        doc_type: str | None = None,
    ) -> list[SearchResult]:
        """Run vector search."""
        try:
            # Generate query embedding
            query_embedding = await self.embeddings.embed_single(query)

            # Build filter
            where_filter = self._build_filter(space_key, doc_type)

            # Query ChromaDB
            results = await self.chroma.query(
                query_embedding=query_embedding,
                n_results=k,
                where=where_filter,
            )

            # Convert to SearchResult
            search_results = []
            if results and results.get("ids") and results["ids"][0]:
                ids = results["ids"][0]
                documents = results["documents"][0] if results.get("documents") else [""] * len(ids)
                metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)
                distances = results["distances"][0] if results.get("distances") else [1.0] * len(ids)

                for chunk_id, content, metadata, distance in zip(
                    ids, documents, metadatas, distances
                ):
                    # Convert distance to similarity score
                    score = 1 - (distance / 2)
                    search_results.append(
                        SearchResult(
                            chunk_id=chunk_id,
                            content=content,
                            score=score,
                            metadata=metadata,
                        )
                    )

            return search_results

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def _build_filter(
        self,
        space_key: str | None = None,
        doc_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Build ChromaDB where filter."""
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

    def _bm25_to_search_results(
        self, bm25_results: list[tuple[str, float]]
    ) -> list[SearchResult]:
        """Convert BM25 results to SearchResult objects."""
        results = []
        for chunk_id, score in bm25_results:
            # Find content and metadata from BM25 index
            try:
                idx = self.bm25.chunk_ids.index(chunk_id)
                content = self.bm25.chunk_contents[idx]
                metadata = self.bm25.chunk_metadata[idx]
            except (ValueError, IndexError):
                content = ""
                metadata = {}

            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    content=content,
                    score=score,
                    metadata=metadata,
                )
            )

        return results

    def _build_results(
        self,
        fused: list[tuple[str, float]],
        bm25_results: list[tuple[str, float]],
        vector_results: list[SearchResult],
    ) -> list[SearchResult]:
        """Build final SearchResult list from fused results."""
        # Create lookup maps
        vector_map = {r.chunk_id: r for r in vector_results}
        bm25_content_map = {}

        for i, chunk_id in enumerate(self.bm25.chunk_ids):
            if i < len(self.bm25.chunk_contents):
                bm25_content_map[chunk_id] = (
                    self.bm25.chunk_contents[i],
                    self.bm25.chunk_metadata[i] if i < len(self.bm25.chunk_metadata) else {},
                )

        results = []
        for chunk_id, rrf_score in fused:
            # Prefer vector result (has fresh content from ChromaDB)
            if chunk_id in vector_map:
                vec_result = vector_map[chunk_id]
                results.append(
                    SearchResult(
                        chunk_id=chunk_id,
                        content=vec_result.content,
                        score=rrf_score,  # Use RRF score
                        metadata=vec_result.metadata,
                    )
                )
            elif chunk_id in bm25_content_map:
                content, metadata = bm25_content_map[chunk_id]
                results.append(
                    SearchResult(
                        chunk_id=chunk_id,
                        content=content,
                        score=rrf_score,
                        metadata=metadata,
                    )
                )
            else:
                # Fallback: ID only
                results.append(
                    SearchResult(
                        chunk_id=chunk_id,
                        content="",
                        score=rrf_score,
                        metadata={},
                    )
                )

        return results

    async def check_health(self) -> dict[str, Any]:
        """Check health of both search systems."""
        chroma_healthy = await self.chroma.check_health()

        return {
            "bm25_indexed": len(self.bm25),
            "bm25_built": self.bm25.is_built,
            "chroma_healthy": chroma_healthy,
            "embedding_provider": self.embeddings.provider_name,
        }
