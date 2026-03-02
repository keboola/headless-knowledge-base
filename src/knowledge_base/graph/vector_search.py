"""HNSW-backed vector search interface for Neo4j.

Replaces Graphiti's default brute-force ``vector.similarity.cosine()`` queries
with HNSW index lookups using ``db.index.vector.queryNodes()`` and
``db.index.vector.queryRelationships()``.

This is injected into the Neo4j driver via ``driver.search_interface`` so
Graphiti's search pipeline uses indexed queries transparently.

**Important**: Graphiti calls ALL SearchInterface methods when one is set,
without try/except fallback for fulltext/episode methods. We must implement
passthrough methods that temporarily remove ourselves from the driver,
delegate to the default code, and restore ourselves afterward.
"""

from __future__ import annotations

import logging
from typing import Any

from graphiti_core.driver.driver import GraphProvider
from graphiti_core.driver.search_interface.search_interface import SearchInterface
from graphiti_core.edges import get_entity_edge_from_record
from graphiti_core.models.edges.edge_db_queries import get_entity_edge_return_query
from graphiti_core.models.nodes.node_db_queries import get_entity_node_return_query
from graphiti_core.nodes import get_entity_node_from_record
from graphiti_core.search import search_utils

from knowledge_base.graph.vector_indices import EDGE_INDEX_NAME, ENTITY_INDEX_NAME

logger = logging.getLogger(__name__)


async def _delegate_to_default(driver: Any, func_name: str, *args: Any, **kwargs: Any) -> Any:
    """Temporarily remove search_interface, call default implementation, restore it.

    This allows methods we don't override to use Graphiti's built-in logic
    (fulltext, BFS, episode search) without infinite recursion.
    """
    saved = driver.search_interface
    driver.search_interface = None
    try:
        func = getattr(search_utils, func_name)
        return await func(driver, *args, **kwargs)
    finally:
        driver.search_interface = saved


class Neo4jVectorSearchInterface(SearchInterface):
    """SearchInterface implementation using HNSW vector indices.

    Overrides vector similarity methods to use HNSW index lookups.
    All other methods (fulltext, BFS, episode, community) delegate back
    to Graphiti's default implementations.
    """

    # ------------------------------------------------------------------
    # HNSW-backed vector similarity searches (the performance fix)
    # ------------------------------------------------------------------

    async def node_similarity_search(
        self,
        driver: Any,
        search_vector: list[float],
        search_filter: Any,
        group_ids: list[str] | None = None,
        limit: int = 100,
        min_score: float = 0.7,
    ) -> list[Any]:
        """Vector similarity search over Entity nodes using HNSW index."""
        # Over-fetch from the index to allow for post-filtering by group_id
        fetch_limit = limit * 3 if group_ids else limit

        query_parts = [
            f"CALL db.index.vector.queryNodes('{ENTITY_INDEX_NAME}', $fetch_limit, $search_vector)",
            "YIELD node AS n, score",
        ]

        where_clauses = ["score > $min_score"]
        params: dict[str, Any] = {
            "search_vector": search_vector,
            "fetch_limit": fetch_limit,
            "min_score": min_score,
            "limit": limit,
        }

        if group_ids is not None:
            where_clauses.append("n.group_id IN $group_ids")
            params["group_ids"] = group_ids

        query_parts.append("WHERE " + " AND ".join(where_clauses))

        return_query = get_entity_node_return_query(GraphProvider.NEO4J)
        query_parts.append(f"RETURN {return_query}")
        query_parts.append("ORDER BY score DESC")
        query_parts.append("LIMIT $limit")

        query = "\n".join(query_parts)

        records, _, _ = await driver.execute_query(
            query,
            routing_="r",
            **params,
        )

        nodes = [get_entity_node_from_record(record, GraphProvider.NEO4J) for record in records]

        logger.debug(
            "HNSW node search: %d results (fetch_limit=%d, limit=%d, min_score=%.2f)",
            len(nodes), fetch_limit, limit, min_score,
        )
        return nodes

    async def edge_similarity_search(
        self,
        driver: Any,
        search_vector: list[float],
        source_node_uuid: str | None,
        target_node_uuid: str | None,
        search_filter: Any,
        group_ids: list[str] | None = None,
        limit: int = 100,
        min_score: float = 0.7,
    ) -> list[Any]:
        """Vector similarity search over RELATES_TO edges using HNSW index."""
        has_filters = group_ids or source_node_uuid or target_node_uuid
        fetch_limit = limit * 3 if has_filters else limit

        query_parts = [
            f"CALL db.index.vector.queryRelationships('{EDGE_INDEX_NAME}', $fetch_limit, $search_vector)",
            "YIELD relationship AS e, score",
            "MATCH (n:Entity)-[e]->(m:Entity)",
        ]

        where_clauses = ["score > $min_score"]
        params: dict[str, Any] = {
            "search_vector": search_vector,
            "fetch_limit": fetch_limit,
            "min_score": min_score,
            "limit": limit,
        }

        if group_ids is not None:
            where_clauses.append("e.group_id IN $group_ids")
            params["group_ids"] = group_ids

        if source_node_uuid is not None:
            where_clauses.append("n.uuid = $source_uuid")
            params["source_uuid"] = source_node_uuid

        if target_node_uuid is not None:
            where_clauses.append("m.uuid = $target_uuid")
            params["target_uuid"] = target_node_uuid

        query_parts.append("WHERE " + " AND ".join(where_clauses))

        # The HNSW index returns unique edges, so no DISTINCT needed.
        # Include score in RETURN so ORDER BY can reference it.
        return_query = get_entity_edge_return_query(GraphProvider.NEO4J)
        query_parts.append(f"RETURN {return_query}, score")
        query_parts.append("ORDER BY score DESC")
        query_parts.append("LIMIT $limit")

        query = "\n".join(query_parts)

        records, _, _ = await driver.execute_query(
            query,
            routing_="r",
            **params,
        )

        edges = [get_entity_edge_from_record(record, GraphProvider.NEO4J) for record in records]

        logger.debug(
            "HNSW edge search: %d results (fetch_limit=%d, limit=%d, min_score=%.2f)",
            len(edges), fetch_limit, limit, min_score,
        )
        return edges

    # ------------------------------------------------------------------
    # Passthrough methods: delegate to Graphiti's default implementations
    # ------------------------------------------------------------------

    async def edge_fulltext_search(
        self,
        driver: Any,
        query: str,
        search_filter: Any,
        group_ids: list[str] | None = None,
        limit: int = 100,
    ) -> list[Any]:
        """Delegate to default Graphiti fulltext search."""
        return await _delegate_to_default(
            driver, "edge_fulltext_search", query, search_filter, group_ids, limit
        )

    async def node_fulltext_search(
        self,
        driver: Any,
        query: str,
        search_filter: Any,
        group_ids: list[str] | None = None,
        limit: int = 100,
    ) -> list[Any]:
        """Delegate to default Graphiti fulltext search."""
        return await _delegate_to_default(
            driver, "node_fulltext_search", query, search_filter, group_ids, limit
        )

    async def episode_fulltext_search(
        self,
        driver: Any,
        query: str,
        search_filter: Any,
        group_ids: list[str] | None = None,
        limit: int = 100,
    ) -> list[Any]:
        """Delegate to default Graphiti fulltext search."""
        return await _delegate_to_default(
            driver, "episode_fulltext_search", query, search_filter, group_ids, limit
        )

    async def community_fulltext_search(
        self,
        driver: Any,
        query: str,
        group_ids: list[str] | None = None,
        limit: int = 100,
    ) -> list[Any]:
        """Delegate to default Graphiti fulltext search."""
        return await _delegate_to_default(
            driver, "community_fulltext_search", query, group_ids, limit
        )

    async def community_similarity_search(
        self,
        driver: Any,
        search_vector: list[float],
        group_ids: list[str] | None = None,
        limit: int = 100,
        min_score: float = 0.6,
    ) -> list[Any]:
        """Delegate to default Graphiti similarity search (no HNSW for communities)."""
        return await _delegate_to_default(
            driver, "community_similarity_search", search_vector, group_ids, limit, min_score
        )
