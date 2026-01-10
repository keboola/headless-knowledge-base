"""Build and manage the knowledge graph using NetworkX."""

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_base.db.models import Entity as EntityModel
from knowledge_base.db.models import Relationship as RelationshipModel
from knowledge_base.db.models import RawPage
from knowledge_base.graph.entity_extractor import EntityExtractor, EntityResolver
from knowledge_base.graph.models import (
    EntityType,
    ExtractedEntities,
    ExtractedEntity,
    GraphEdge,
    GraphNode,
    RelationType,
)

if TYPE_CHECKING:
    from knowledge_base.rag.llm import BaseLLM

logger = logging.getLogger(__name__)


class KnowledgeGraphBuilder:
    """Build and maintain a knowledge graph from documents."""

    def __init__(self, llm: "BaseLLM", session: Session):
        """Initialize the graph builder.

        Args:
            llm: LLM for entity extraction
            session: Database session
        """
        self.extractor = EntityExtractor(llm)
        self.resolver = EntityResolver()
        self.session = session
        self.graph = nx.DiGraph()

    async def process_document(
        self,
        page_id: str,
        content: str,
        author: str | None = None,
        space_key: str | None = None,
        topics: list[str] | None = None,
    ) -> list[ExtractedEntity]:
        """Process a document and add to knowledge graph.

        Args:
            page_id: Document page ID
            content: Document content
            author: Document author (optional)
            space_key: Confluence space key (optional)
            topics: Document topics from metadata (optional)

        Returns:
            List of extracted entities
        """
        # Extract entities
        extracted = await self.extractor.extract(content)

        if extracted.is_empty() and not author and not space_key:
            logger.debug(f"No entities found in {page_id}")
            return []

        # Convert to entity list and resolve
        entities = extracted.to_entity_list()
        resolved_entities = self.resolver.resolve_all(entities)

        # Add document node
        self._add_page_node(page_id)

        # Add entity nodes and relationships
        for entity in resolved_entities:
            self._add_entity_node(entity)
            self._add_relationship(page_id, entity)

        # Add author relationship
        if author:
            author_entity = ExtractedEntity(name=author, entity_type=EntityType.PERSON)
            self._add_entity_node(author_entity)
            self._add_relationship(
                page_id, author_entity, RelationType.AUTHORED_BY, weight=2.0
            )

        # Add space relationship
        if space_key:
            space_entity = ExtractedEntity(name=space_key, entity_type=EntityType.TEAM)
            self._add_entity_node(space_entity)
            self._add_relationship(
                page_id, space_entity, RelationType.BELONGS_TO_SPACE, weight=1.5
            )

        # Add topic relationships
        if topics:
            for topic in topics:
                topic_entity = ExtractedEntity(name=topic, entity_type=EntityType.TOPIC)
                self._add_entity_node(topic_entity)
                self._add_relationship(
                    page_id, topic_entity, RelationType.RELATED_TO_TOPIC, weight=1.0
                )

        return resolved_entities

    def _add_page_node(self, page_id: str) -> None:
        """Add a page node to the graph."""
        node_id = f"page:{page_id}"
        if node_id not in self.graph:
            self.graph.add_node(node_id, node_type="page", name=page_id)

    def _add_entity_node(self, entity: ExtractedEntity) -> None:
        """Add an entity node to the graph."""
        entity_id = entity.entity_id
        if entity_id not in self.graph:
            self.graph.add_node(
                entity_id,
                node_type=entity.entity_type.value,
                name=entity.name,
                aliases=entity.aliases,
            )
        else:
            # Update aliases
            existing_aliases = self.graph.nodes[entity_id].get("aliases", [])
            all_aliases = list(set(existing_aliases + entity.aliases))
            self.graph.nodes[entity_id]["aliases"] = all_aliases

    def _add_relationship(
        self,
        page_id: str,
        entity: ExtractedEntity,
        relation_type: RelationType | None = None,
        weight: float = 1.0,
    ) -> None:
        """Add a relationship edge to the graph."""
        source_id = f"page:{page_id}"
        target_id = entity.entity_id

        # Determine relation type if not specified
        if relation_type is None:
            relation_type = RelationType(f"mentions_{entity.entity_type.value}")

        # Add or update edge
        if self.graph.has_edge(source_id, target_id):
            # Increase weight for repeated mentions
            self.graph[source_id][target_id]["weight"] += weight
        else:
            self.graph.add_edge(
                source_id,
                target_id,
                relation_type=relation_type.value,
                weight=weight,
            )

    def save_to_database(self) -> tuple[int, int]:
        """Save the graph to database.

        Returns:
            Tuple of (entities_saved, relationships_saved)
        """
        entities_saved = 0
        relationships_saved = 0

        # Save entities
        for node_id, data in self.graph.nodes(data=True):
            if data.get("node_type") != "page":
                entity = self._get_or_create_entity(node_id, data)
                if entity:
                    entities_saved += 1

        # Save relationships
        for source_id, target_id, data in self.graph.edges(data=True):
            rel = self._create_relationship(source_id, target_id, data)
            if rel:
                relationships_saved += 1

        self.session.commit()
        logger.info(f"Saved {entities_saved} entities and {relationships_saved} relationships")

        return entities_saved, relationships_saved

    def _get_or_create_entity(self, entity_id: str, data: dict) -> EntityModel | None:
        """Get or create an entity in the database."""
        existing = self.session.execute(
            select(EntityModel).where(EntityModel.entity_id == entity_id)
        ).scalar_one_or_none()

        if existing:
            # Update source count
            existing.source_count += 1
            # Merge aliases
            current_aliases = json.loads(existing.aliases or "[]")
            new_aliases = data.get("aliases", [])
            all_aliases = list(set(current_aliases + new_aliases))
            existing.aliases = json.dumps(all_aliases)
            return existing

        entity = EntityModel(
            entity_id=entity_id,
            name=data.get("name", entity_id),
            entity_type=data.get("node_type", "unknown"),
            aliases=json.dumps(data.get("aliases", [])),
            source_count=1,
        )
        self.session.add(entity)
        return entity

    def _create_relationship(
        self, source_id: str, target_id: str, data: dict
    ) -> RelationshipModel | None:
        """Create a relationship in the database."""
        # Determine source type
        source_type = "page" if source_id.startswith("page:") else "entity"
        actual_source = source_id.replace("page:", "")

        rel = RelationshipModel(
            source_id=actual_source,
            source_type=source_type,
            target_id=target_id,
            relation_type=data.get("relation_type", "mentions"),
            weight=data.get("weight", 1.0),
        )
        self.session.add(rel)
        return rel

    def load_from_database(self) -> None:
        """Load the graph from database."""
        self.graph.clear()

        # Load entities as nodes
        entities = self.session.execute(select(EntityModel)).scalars().all()
        for entity in entities:
            self.graph.add_node(
                entity.entity_id,
                node_type=entity.entity_type,
                name=entity.name,
                aliases=json.loads(entity.aliases or "[]"),
            )

        # Load pages as nodes
        pages = self.session.execute(select(RawPage)).scalars().all()
        for page in pages:
            self.graph.add_node(
                f"page:{page.page_id}",
                node_type="page",
                name=page.title,
            )

        # Load relationships as edges
        relationships = self.session.execute(select(RelationshipModel)).scalars().all()
        for rel in relationships:
            source = f"page:{rel.source_id}" if rel.source_type == "page" else rel.source_id
            self.graph.add_edge(
                source,
                rel.target_id,
                relation_type=rel.relation_type,
                weight=rel.weight,
            )

        logger.info(
            f"Loaded graph with {self.graph.number_of_nodes()} nodes "
            f"and {self.graph.number_of_edges()} edges"
        )

    def get_stats(self) -> dict:
        """Get graph statistics."""
        node_types = {}
        for _, data in self.graph.nodes(data=True):
            node_type = data.get("node_type", "unknown")
            node_types[node_type] = node_types.get(node_type, 0) + 1

        relation_types = {}
        for _, _, data in self.graph.edges(data=True):
            rel_type = data.get("relation_type", "unknown")
            relation_types[rel_type] = relation_types.get(rel_type, 0) + 1

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "node_types": node_types,
            "relation_types": relation_types,
        }

    def export_graphml(self, filepath: str) -> None:
        """Export graph to GraphML format for visualization."""
        nx.write_graphml(self.graph, filepath)
        logger.info(f"Graph exported to {filepath}")
