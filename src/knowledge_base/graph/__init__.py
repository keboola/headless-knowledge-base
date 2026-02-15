"""Knowledge graph module using Graphiti framework with Neo4j backend.

This module provides entity extraction, knowledge graph building,
and multi-hop reasoning via the Graphiti temporal knowledge graph.
"""

from knowledge_base.config import settings

from knowledge_base.graph.entity_extractor import EntityResolver
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


__all__ = [
    # Models
    "EntityResolver",
    "EntityType",
    "ExtractedEntities",
    "ExtractedEntity",
    "GraphEdge",
    "GraphNode",
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
]
