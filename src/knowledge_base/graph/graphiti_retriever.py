"""Query the knowledge graph using Graphiti.

This module provides a Graphiti-based graph retriever that is the primary
search interface for the knowledge base (ChromaDB has been eliminated).

Key features:
- Uses Graphiti's search() for hybrid retrieval (semantic + BM25 + graph)
- Returns SearchResult objects compatible with existing API
- Supports metadata filtering (space_key, doc_type, quality_score)
- Supports temporal queries (bi-temporal model)
- Can traverse the graph for multi-hop reasoning
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from knowledge_base.config import settings
from knowledge_base.graph.entity_schemas import GraphEntityType
from knowledge_base.graph.graphiti_client import get_graphiti_client, GraphitiClientError

if TYPE_CHECKING:
    from graphiti_core import Graphiti

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result (compatible with VectorRetriever.SearchResult)."""

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
        """Quality score from Graphiti metadata (source of truth)."""
        return self.metadata.get("quality_score", 100.0)

    @property
    def owner(self) -> str:
        """Document owner from Graphiti metadata."""
        return self.metadata.get("owner", "")


class GraphitiRetriever:
    """Retrieve related documents and entities using Graphiti.

    Provides the same interface as GraphRetriever but uses Graphiti
    for graph traversal and search.
    """

    def __init__(self, group_id: str | None = None):
        """Initialize the Graphiti retriever.

        Args:
            group_id: Graphiti group ID for multi-tenancy (defaults to settings)
        """
        self.group_id = group_id or settings.GRAPH_GROUP_ID
        self.client = get_graphiti_client()
        self._graphiti: "Graphiti | None" = None

    async def _get_graphiti(self) -> "Graphiti":
        """Get the Graphiti instance lazily."""
        if self._graphiti is None:
            self._graphiti = await self.client.get_client()
        return self._graphiti

    @property
    def is_enabled(self) -> bool:
        """Check if Graphiti retrieval is enabled."""
        return settings.GRAPH_ENABLE_GRAPHITI

    # =========================================================================
    # New methods for Graphiti-only architecture (ChromaDB eliminated)
    # =========================================================================

    def _parse_metadata(self, source_description: str | None) -> dict[str, Any]:
        """Parse JSON metadata from Graphiti source_description.

        Args:
            source_description: JSON string or pipe-delimited legacy format

        Returns:
            Parsed metadata dict
        """
        if not source_description:
            return {}

        # Try JSON first (new format)
        try:
            return json.loads(source_description)
        except json.JSONDecodeError:
            pass

        # Fall back to legacy pipe-delimited format
        metadata = {}
        if 'Page ID:' in source_description:
            parts = source_description.split('Page ID:')
            if len(parts) > 1:
                metadata['page_id'] = parts[1].strip().split()[0]
        if 'Title:' in source_description:
            parts = source_description.split('Title:')
            if len(parts) > 1:
                metadata['page_title'] = parts[1].split('|')[0].strip()
        if 'Space:' in source_description:
            parts = source_description.split('Space:')
            if len(parts) > 1:
                metadata['space_key'] = parts[1].split('|')[0].strip()
        if 'URL:' in source_description:
            parts = source_description.split('URL:')
            if len(parts) > 1:
                metadata['url'] = parts[1].split('|')[0].strip()
        if 'Chunk:' in source_description:
            parts = source_description.split('Chunk:')
            if len(parts) > 1:
                metadata['chunk_id'] = parts[1].split('|')[0].strip()

        return metadata

    def _to_search_result(self, graphiti_result: Any) -> SearchResult:
        """Convert a Graphiti search result to SearchResult.

        Args:
            graphiti_result: Result from Graphiti search

        Returns:
            SearchResult object
        """
        # Parse metadata from source_description
        source_desc = getattr(graphiti_result, 'source_description', None)
        metadata = self._parse_metadata(source_desc)

        # Get chunk_id from metadata or episode name
        chunk_id = metadata.get('chunk_id', '')
        if not chunk_id and hasattr(graphiti_result, 'name'):
            chunk_id = graphiti_result.name

        # Get content
        content = getattr(graphiti_result, 'content', '') or ''

        # Get score
        score = getattr(graphiti_result, 'score', 1.0)

        return SearchResult(
            chunk_id=chunk_id,
            content=content,
            score=score,
            metadata=metadata,
        )

    async def search_chunks(
        self,
        query: str,
        num_results: int = 10,
        space_key: str | None = None,
        doc_type: str | None = None,
        min_quality_score: float | None = None,
    ) -> list[SearchResult]:
        """Search for chunks and return SearchResult objects.

        This is the primary search interface (replacing ChromaDB search).

        Args:
            query: Search query
            num_results: Maximum number of results
            space_key: Optional filter by Confluence space
            doc_type: Optional filter by document type
            min_quality_score: Optional minimum quality score (0-100)

        Returns:
            List of SearchResult objects with full metadata
        """
        if not self.is_enabled:
            logger.debug("Graphiti retrieval disabled")
            return []

        try:
            graphiti = await self._get_graphiti()

            # Over-fetch to account for filtering
            fetch_count = num_results * 3 if (space_key or doc_type or min_quality_score) else num_results

            results = await graphiti.search(
                query=query,
                num_results=fetch_count,
                group_ids=[self.group_id],
            )

            # Convert and filter results
            search_results = []
            for result in results:
                sr = self._to_search_result(result)

                # Skip deleted chunks
                if sr.metadata.get('deleted'):
                    continue

                # Apply filters
                if space_key and sr.metadata.get('space_key') != space_key:
                    continue
                if doc_type and sr.metadata.get('doc_type') != doc_type:
                    continue
                if min_quality_score and sr.quality_score < min_quality_score:
                    continue

                search_results.append(sr)

                if len(search_results) >= num_results:
                    break

            logger.debug(f"Graphiti search_chunks returned {len(search_results)} results for: {query[:50]}...")
            return search_results

        except GraphitiClientError as e:
            logger.error(f"Graphiti search failed: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Graphiti search: {e}")
            return []

    async def search_with_quality_boost(
        self,
        query: str,
        num_results: int = 10,
        quality_boost_weight: float = 0.2,
        space_key: str | None = None,
        doc_type: str | None = None,
    ) -> list[SearchResult]:
        """Search with quality score boosting applied.

        Args:
            query: Search query
            num_results: Maximum number of results
            quality_boost_weight: Weight for quality boost (0-1)
            space_key: Optional filter by Confluence space
            doc_type: Optional filter by document type

        Returns:
            List of SearchResult objects, re-ranked by quality-boosted score
        """
        # Get more results to re-rank
        results = await self.search_chunks(
            query=query,
            num_results=num_results * 2,
            space_key=space_key,
            doc_type=doc_type,
        )

        if not results:
            return []

        # Apply quality boost
        # normalized_quality = quality_score / 100 (0-1)
        # boosted_score = score * (1 + quality_boost_weight * (normalized_quality - 0.5))
        boosted_results = []
        for r in results:
            normalized_quality = r.quality_score / 100.0
            quality_factor = 1 + quality_boost_weight * (normalized_quality - 0.5)
            boosted_score = r.score * quality_factor

            boosted_results.append(SearchResult(
                chunk_id=r.chunk_id,
                content=r.content,
                score=boosted_score,
                metadata=r.metadata,
            ))

        # Sort by boosted score
        boosted_results.sort(key=lambda x: x.score, reverse=True)

        return boosted_results[:num_results]

    async def search(
        self,
        query: str,
        num_results: int = 10,
        include_edges: bool = True,
    ) -> list[dict[str, Any]]:
        """Search the graph for relevant information.

        Uses Graphiti's hybrid search combining:
        - Semantic similarity
        - BM25 keyword matching
        - Graph relationships

        Args:
            query: Search query
            num_results: Maximum number of results
            include_edges: Whether to include relationship context

        Returns:
            List of search result dicts with entity/episode info
        """
        if not self.is_enabled:
            logger.debug("Graphiti retrieval disabled")
            return []

        try:
            graphiti = await self._get_graphiti()

            # Use Graphiti's search
            results = await graphiti.search(
                query=query,
                num_results=num_results,
                group_ids=[self.group_id],
            )

            # Convert to standardized format
            search_results = []
            for result in results:
                result_dict = {
                    "id": str(result.uuid) if hasattr(result, 'uuid') else str(id(result)),
                    "name": result.name if hasattr(result, 'name') else str(result),
                    "content": result.content if hasattr(result, 'content') else "",
                    "score": result.score if hasattr(result, 'score') else 1.0,
                    "source": "graphiti",
                }

                # Add source tracking if available
                if hasattr(result, 'source_description'):
                    result_dict["source_description"] = result.source_description
                    # Try to extract page_id from source
                    result_dict["page_id"] = self._extract_page_id(result.source_description)

                # Add edge context if requested
                if include_edges and hasattr(result, 'edges'):
                    result_dict["edges"] = [
                        {
                            "relation": edge.relation if hasattr(edge, 'relation') else "related_to",
                            "target": edge.target if hasattr(edge, 'target') else str(edge),
                        }
                        for edge in result.edges
                    ]

                search_results.append(result_dict)

            logger.debug(f"Graphiti search returned {len(search_results)} results for: {query[:50]}...")
            return search_results

        except GraphitiClientError as e:
            logger.error(f"Graphiti search failed: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Graphiti search: {e}")
            return []

    def _extract_page_id(self, source_description: str) -> str | None:
        """Extract page ID from Graphiti source description."""
        if not source_description:
            return None

        if 'Page ID:' in source_description:
            parts = source_description.split('Page ID:')
            if len(parts) > 1:
                return parts[1].strip().split()[0]

        return None

    async def get_related_documents(
        self,
        doc_id: str,
        hops: int = 2,
        max_results: int = 10,
    ) -> list[str]:
        """Get related documents via graph traversal.

        Same interface as NetworkX-based GraphRetriever.get_related_documents()

        Args:
            doc_id: Starting document page_id
            hops: Number of hops to traverse (for future multi-hop support)
            max_results: Maximum documents to return

        Returns:
            List of related page_ids
        """
        if not self.is_enabled:
            return []

        try:
            # Search for documents related to this one
            results = await self.search(
                query=f"documents related to page {doc_id}",
                num_results=max_results * 2,
            )

            # Extract unique page IDs
            related_pages = []
            seen = {doc_id}  # Exclude the source document

            for result in results:
                page_id = result.get("page_id")
                if page_id and page_id not in seen:
                    related_pages.append(page_id)
                    seen.add(page_id)

                if len(related_pages) >= max_results:
                    break

            return related_pages

        except Exception as e:
            logger.error(f"Failed to get related documents for {doc_id}: {e}")
            return []

    async def find_by_entity(
        self,
        entity_name: str,
        entity_type: str | GraphEntityType | None = None,
        max_results: int = 10,
    ) -> list[str]:
        """Find all documents mentioning an entity.

        Same interface as NetworkX-based GraphRetriever.find_by_entity()

        Args:
            entity_name: Name of the entity to search for
            entity_type: Optional entity type filter

        Returns:
            List of page_ids
        """
        if not self.is_enabled:
            return []

        try:
            # Build search query
            if entity_type:
                type_str = entity_type.value if hasattr(entity_type, 'value') else str(entity_type)
                query = f"{type_str} {entity_name}"
            else:
                query = entity_name

            results = await self.search(query=query, num_results=max_results * 2)

            # Extract page IDs from results
            page_ids = []
            seen = set()

            for result in results:
                page_id = result.get("page_id")
                if page_id and page_id not in seen:
                    page_ids.append(page_id)
                    seen.add(page_id)

                if len(page_ids) >= max_results:
                    break

            return page_ids

        except Exception as e:
            logger.error(f"Failed to find documents for entity '{entity_name}': {e}")
            return []

    async def get_entity_documents(
        self,
        entity_name: str,
        entity_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all documents for an entity with details.

        Same interface as NetworkX-based GraphRetriever.get_entity_documents()

        Args:
            entity_name: Entity name to search for
            entity_type: Optional entity type filter

        Returns:
            List of dicts with page details
        """
        if not self.is_enabled:
            return []

        try:
            results = await self.search(
                query=entity_name,
                num_results=20,
                include_edges=True,
            )

            # Convert to standardized format
            documents = []
            for result in results:
                page_id = result.get("page_id")
                if page_id:
                    doc = {
                        "page_id": page_id,
                        "relation_type": "mentions",
                        "weight": result.get("score", 1.0),
                    }

                    # Add additional info if available
                    if "source_description" in result:
                        source = result["source_description"]
                        if "Title:" in source:
                            doc["title"] = source.split("Title:")[1].split("|")[0].strip()
                        if "URL:" in source:
                            doc["url"] = source.split("URL:")[1].split("|")[0].strip()
                        if "Space:" in source:
                            doc["space_key"] = source.split("Space:")[1].split("|")[0].strip()

                    documents.append(doc)

            return documents

        except Exception as e:
            logger.error(f"Failed to get documents for entity '{entity_name}': {e}")
            return []

    async def get_document_entities(
        self,
        page_id: str,
    ) -> list[dict[str, Any]]:
        """Get all entities for a document.

        Same interface as NetworkX-based GraphRetriever.get_document_entities()

        Args:
            page_id: Document page ID

        Returns:
            List of dicts with entity details
        """
        if not self.is_enabled:
            return []

        try:
            # Search for entities mentioned in this document
            results = await self.search(
                query=f"entities in document {page_id}",
                num_results=20,
                include_edges=True,
            )

            # Extract entity information
            entities = []
            for result in results:
                entity = {
                    "entity_id": result.get("id"),
                    "name": result.get("name", "unknown"),
                    "entity_type": "unknown",  # Graphiti may not expose this directly
                    "relation_type": "mentions",
                    "weight": result.get("score", 1.0),
                }

                # Try to infer type from edges or content
                if "edges" in result:
                    for edge in result["edges"]:
                        if edge.get("relation"):
                            entity["relation_type"] = edge["relation"]
                            break

                entities.append(entity)

            return entities

        except Exception as e:
            logger.error(f"Failed to get entities for document {page_id}: {e}")
            return []

    async def get_common_entities(
        self,
        page_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Find entities common to multiple documents.

        Useful for understanding what topics connect search results.

        Args:
            page_ids: List of document page IDs

        Returns:
            List of common entities with occurrence count
        """
        if not self.is_enabled or not page_ids:
            return []

        try:
            # Get entities for each document
            entity_counts: dict[str, dict] = {}

            for page_id in page_ids:
                entities = await self.get_document_entities(page_id)
                for entity in entities:
                    entity_id = entity.get("entity_id")
                    if entity_id:
                        if entity_id not in entity_counts:
                            entity_counts[entity_id] = {
                                "entity_id": entity_id,
                                "name": entity.get("name", "unknown"),
                                "entity_type": entity.get("entity_type", "unknown"),
                                "count": 0,
                                "total_weight": 0.0,
                            }
                        entity_counts[entity_id]["count"] += 1
                        entity_counts[entity_id]["total_weight"] += entity.get("weight", 1.0)

            # Filter to entities appearing in multiple docs
            common = [e for e in entity_counts.values() if e["count"] > 1]
            common.sort(key=lambda x: (x["count"], x["total_weight"]), reverse=True)

            return common

        except Exception as e:
            logger.error(f"Failed to get common entities: {e}")
            return []

    async def expand_query_with_entities(
        self,
        query: str,
        page_ids: list[str],
        top_k: int = 3,
    ) -> list[str]:
        """Expand search by finding additional docs through common entities.

        This is the core of graph expansion for search.
        Per the migration plan, this is opt-in (not default).

        Args:
            query: Original search query
            page_ids: Page IDs from initial search
            top_k: Number of additional pages to return

        Returns:
            Additional page_ids to include in results
        """
        if not self.is_enabled or not page_ids:
            return []

        try:
            # Find common entities
            common_entities = await self.get_common_entities(page_ids)

            if not common_entities:
                return []

            # Get pages from top entities
            additional_pages = set()
            existing_pages = set(page_ids)

            for entity in common_entities[:5]:  # Top 5 entities
                entity_pages = await self.find_by_entity(
                    entity["name"],
                    entity.get("entity_type"),
                )
                for page_id in entity_pages:
                    if page_id not in existing_pages:
                        additional_pages.add(page_id)

            # Score by how many common entities they share
            scored = []
            common_entity_ids = {e["entity_id"] for e in common_entities}

            for page_id in additional_pages:
                page_entities = await self.get_document_entities(page_id)
                page_entity_ids = {e.get("entity_id") for e in page_entities if e.get("entity_id")}
                overlap = len(page_entity_ids & common_entity_ids)
                if overlap > 0:
                    scored.append((page_id, overlap))

            scored.sort(key=lambda x: x[1], reverse=True)
            return [page_id for page_id, _ in scored[:top_k]]

        except Exception as e:
            logger.error(f"Failed to expand query: {e}")
            return []

    async def get_all_episodes(self, limit: int = 10000) -> list[dict[str, Any]]:
        """Get all chunk episodes from Graphiti.

        Used for bulk operations like quality score recalculation.

        Args:
            limit: Maximum number of episodes to retrieve

        Returns:
            List of episode dicts with chunk_id and metadata
        """
        if not self.is_enabled:
            return []

        try:
            graphiti = await self._get_graphiti()

            # Search with empty query to get all episodes
            # Note: This may need adjustment based on actual Graphiti API
            results = await graphiti.search(
                query="*",  # Wildcard to match all
                num_results=limit,
                group_ids=[self.group_id],
            )

            episodes = []
            for result in results:
                metadata = self._parse_metadata(
                    getattr(result, 'source_description', None)
                )

                # Skip deleted chunks
                if metadata.get('deleted'):
                    continue

                chunk_id = metadata.get('chunk_id', '')
                if not chunk_id and hasattr(result, 'name'):
                    chunk_id = result.name

                episodes.append({
                    "chunk_id": chunk_id,
                    "content": getattr(result, 'content', ''),
                    "metadata": metadata,
                })

            return episodes

        except Exception as e:
            logger.error(f"Failed to get all episodes: {e}")
            return []

    async def get_recent_episodes(
        self,
        days: int = 7,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        """Get episodes created/modified in the last N days.

        Args:
            days: Number of days to look back
            limit: Maximum number of episodes to retrieve

        Returns:
            List of episode dicts with chunk_id and metadata
        """
        from datetime import datetime, timedelta

        if not self.is_enabled:
            return []

        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            cutoff_iso = cutoff.isoformat()

            # Get all episodes and filter by date
            all_episodes = await self.get_all_episodes(limit=limit)

            recent = []
            for ep in all_episodes:
                metadata = ep.get("metadata", {})
                created_at = metadata.get("created_at", "")
                updated_at = metadata.get("updated_at", "")

                # Check if created or updated recently
                if (created_at and created_at >= cutoff_iso) or \
                   (updated_at and updated_at >= cutoff_iso):
                    recent.append(ep)

            return recent

        except Exception as e:
            logger.error(f"Failed to get recent episodes: {e}")
            return []

    async def close(self) -> None:
        """Close the Graphiti connection."""
        await self.client.close()
        self._graphiti = None


# Factory function for getting a retriever instance
_default_retriever: GraphitiRetriever | None = None


def get_graphiti_retriever() -> GraphitiRetriever:
    """Get the default GraphitiRetriever instance.

    Returns:
        GraphitiRetriever configured from settings
    """
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = GraphitiRetriever()
    return _default_retriever
