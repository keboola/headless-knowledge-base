"""Knowledge graph module for entity extraction and multi-hop reasoning.

This module provides two implementations:

1. **Legacy (NetworkX + SQLite)**: The original implementation using
   NetworkX for in-memory graph and SQLAlchemy for persistence.

2. **Graphiti (Kuzu/Neo4j)**: The new implementation using Graphiti
   framework with Kuzu (embedded, dev) or Neo4j (production) backends.

The implementation is selected via feature flags in settings:
- GRAPH_ENABLE_GRAPHITI: Master switch for Graphiti
- GRAPH_DUAL_WRITE: Write to both old and new during transition
- GRAPH_COMPARE_MODE: Log comparison metrics between old/new

During the migration period, both implementations are available.
"""

from knowledge_base.config import settings

# Legacy implementation (NetworkX + SQLite)
from knowledge_base.graph.entity_extractor import EntityExtractor, EntityResolver
from knowledge_base.graph.graph_builder import KnowledgeGraphBuilder
from knowledge_base.graph.graph_retriever import GraphRetriever
from knowledge_base.graph.models import (
    EntityType,
    ExtractedEntities,
    ExtractedEntity,
    GraphEdge,
    GraphNode,
    RelationType,
)

# Graphiti implementation (Kuzu/Neo4j)
from knowledge_base.graph.graphiti_client import (
    GraphitiClient,
    GraphitiClientError,
    GraphitiConnectionError,
    get_graphiti_client,
    get_graphiti,
)
from knowledge_base.graph.graphiti_builder import (
    GraphitiBuilder,
    get_graphiti_builder,
)
from knowledge_base.graph.graphiti_retriever import (
    GraphitiRetriever,
    get_graphiti_retriever,
)
from knowledge_base.graph.entity_schemas import (
    GraphEntityType,
    GraphRelationType,
    BaseGraphEntity,
    PersonEntity,
    TeamEntity,
    ProductEntity,
    LocationEntity,
    TopicEntity,
    DocumentEntity,
    GraphRelationship,
    entity_type_to_schema,
    create_entity,
)


def get_graph_builder(llm=None, session=None):
    """Get the appropriate graph builder based on feature flags.

    During the migration period, this may return either:
    - KnowledgeGraphBuilder (legacy NetworkX)
    - GraphitiBuilder (new Graphiti)

    Or both in dual-write mode.

    Args:
        llm: LLM instance (required for legacy builder)
        session: Database session (required for legacy builder)

    Returns:
        Graph builder instance(s)
    """
    if settings.GRAPH_ENABLE_GRAPHITI:
        return get_graphiti_builder()

    # Legacy requires llm and session
    if llm is None or session is None:
        raise ValueError("Legacy graph builder requires llm and session arguments")
    return KnowledgeGraphBuilder(llm=llm, session=session)


def get_graph_retriever(graph=None, session=None):
    """Get the appropriate graph retriever based on feature flags.

    Args:
        graph: NetworkX graph (for legacy retriever)
        session: Database session (for legacy retriever)

    Returns:
        Graph retriever instance
    """
    if settings.GRAPH_ENABLE_GRAPHITI:
        return get_graphiti_retriever()

    # Legacy requires graph
    if graph is None:
        raise ValueError("Legacy graph retriever requires graph argument")
    return GraphRetriever(graph=graph, session=session)


__all__ = [
    # Legacy implementation
    "EntityExtractor",
    "EntityResolver",
    "EntityType",
    "ExtractedEntities",
    "ExtractedEntity",
    "GraphEdge",
    "GraphNode",
    "GraphRetriever",
    "KnowledgeGraphBuilder",
    "RelationType",
    # Graphiti implementation
    "GraphitiClient",
    "GraphitiClientError",
    "GraphitiConnectionError",
    "GraphitiBuilder",
    "GraphitiRetriever",
    "get_graphiti_client",
    "get_graphiti",
    "get_graphiti_builder",
    "get_graphiti_retriever",
    # Entity schemas
    "GraphEntityType",
    "GraphRelationType",
    "BaseGraphEntity",
    "PersonEntity",
    "TeamEntity",
    "ProductEntity",
    "LocationEntity",
    "TopicEntity",
    "DocumentEntity",
    "GraphRelationship",
    "entity_type_to_schema",
    "create_entity",
    # Factory functions
    "get_graph_builder",
    "get_graph_retriever",
]
