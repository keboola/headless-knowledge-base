"""HNSW vector index management for Neo4j.

Graphiti-core v0.26.3 does NOT create vector indices -- all vector similarity
searches use brute-force ``vector.similarity.cosine()`` which scans every
node/edge. With 196K entities and 400K edges, this takes ~2 minutes per query.

This module creates HNSW vector indices that reduce vector search from O(N)
to O(log N), bringing query time from minutes to milliseconds.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graphiti_core.driver.neo4j_driver import Neo4jDriver

logger = logging.getLogger(__name__)

# Index definitions -- dimension must match Vertex AI text-embedding-005 (768-dim)
VECTOR_INDEX_DIMENSION = 768
VECTOR_SIMILARITY_FUNCTION = "cosine"

ENTITY_INDEX_NAME = "entity_name_embedding"
EDGE_INDEX_NAME = "edge_fact_embedding"


async def create_vector_indices(driver: Neo4jDriver) -> None:
    """Create HNSW vector indices on Entity nodes and RELATES_TO edges.

    Uses ``IF NOT EXISTS`` so calls are idempotent. Safe to call on every
    Graphiti client initialization.

    Args:
        driver: Graphiti Neo4j driver instance.
    """
    entity_query = (
        f"CREATE VECTOR INDEX {ENTITY_INDEX_NAME} IF NOT EXISTS "
        "FOR (n:Entity) ON (n.name_embedding) "
        "OPTIONS { indexConfig: { "
        f"`vector.dimensions`: {VECTOR_INDEX_DIMENSION}, "
        f"`vector.similarity_function`: '{VECTOR_SIMILARITY_FUNCTION}' "
        "} }"
    )

    edge_query = (
        f"CREATE VECTOR INDEX {EDGE_INDEX_NAME} IF NOT EXISTS "
        "FOR ()-[e:RELATES_TO]-() ON (e.fact_embedding) "
        "OPTIONS { indexConfig: { "
        f"`vector.dimensions`: {VECTOR_INDEX_DIMENSION}, "
        f"`vector.similarity_function`: '{VECTOR_SIMILARITY_FUNCTION}' "
        "} }"
    )

    logger.info("Creating HNSW vector index: %s (Entity.name_embedding)", ENTITY_INDEX_NAME)
    await driver.execute_query(entity_query)

    logger.info("Creating HNSW vector index: %s (RELATES_TO.fact_embedding)", EDGE_INDEX_NAME)
    await driver.execute_query(edge_query)

    logger.info("Vector index creation commands issued (IF NOT EXISTS)")


async def check_vector_indices(driver: Neo4jDriver) -> dict[str, str]:
    """Check the status of vector indices.

    Returns:
        Dict mapping index name to state (e.g. ``{"entity_name_embedding": "ONLINE"}``).
        Missing indices are not included.
    """
    query = "SHOW INDEXES WHERE type = 'VECTOR' RETURN name, state"
    records, _, _ = await driver.execute_query(query)

    result: dict[str, str] = {}
    for record in records:
        result[record["name"]] = record["state"]

    logger.info("Vector index status: %s", result)
    return result


async def verify_data_quality(driver: Neo4jDriver) -> dict[str, int]:
    """Run quick data quality checks after write operations.

    Returns:
        Dict with check names and counts of bad records found.
    """
    checks = {
        "empty_name_entities": (
            "MATCH (n:Entity) WHERE n.name IS NULL OR trim(n.name) = '' "
            "RETURN count(n) AS cnt"
        ),
        "bad_embedding_entities": (
            "MATCH (n:Entity) WHERE n.name_embedding IS NOT NULL "
            "AND size(n.name_embedding) <> 768 AND size(n.name_embedding) > 0 "
            "RETURN count(n) AS cnt"
        ),
        "empty_embedding_entities": (
            "MATCH (n:Entity) WHERE n.name_embedding IS NOT NULL "
            "AND size(n.name_embedding) = 0 "
            "RETURN count(n) AS cnt"
        ),
    }

    results: dict[str, int] = {}
    for name, query in checks.items():
        try:
            records, _, _ = await driver.execute_query(query)
            count = records[0]["cnt"] if records else 0
            results[name] = count
            if count > 0:
                logger.warning("Data quality issue: %s = %d", name, count)
        except Exception as e:
            logger.error("Data quality check %s failed: %s", name, e)
            results[name] = -1

    return results
