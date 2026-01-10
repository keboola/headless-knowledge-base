"""Data models for knowledge graph entities and relationships."""

from dataclasses import dataclass, field
from enum import Enum


class EntityType(str, Enum):
    """Types of entities that can be extracted from documents."""

    PERSON = "person"
    TEAM = "team"
    PRODUCT = "product"
    LOCATION = "location"
    TOPIC = "topic"


class RelationType(str, Enum):
    """Types of relationships in the knowledge graph."""

    MENTIONS_PERSON = "mentions_person"
    MENTIONS_TEAM = "mentions_team"
    MENTIONS_PRODUCT = "mentions_product"
    MENTIONS_LOCATION = "mentions_location"
    AUTHORED_BY = "authored_by"
    BELONGS_TO_SPACE = "belongs_to_space"
    RELATED_TO_TOPIC = "related_to_topic"


@dataclass
class ExtractedEntity:
    """An entity extracted from document content."""

    name: str
    entity_type: EntityType
    aliases: list[str] = field(default_factory=list)
    context: str | None = None

    @property
    def entity_id(self) -> str:
        """Generate canonical entity ID from name and type."""
        # Normalize: lowercase, replace spaces with underscores
        normalized = self.name.lower().replace(" ", "_").replace("-", "_")
        # Remove special characters
        normalized = "".join(c for c in normalized if c.isalnum() or c == "_")
        return f"{self.entity_type.value}:{normalized}"


@dataclass
class ExtractedEntities:
    """Collection of entities extracted from a document."""

    people: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)

    def to_entity_list(self) -> list[ExtractedEntity]:
        """Convert to list of ExtractedEntity objects."""
        entities = []
        for name in self.people:
            entities.append(ExtractedEntity(name=name, entity_type=EntityType.PERSON))
        for name in self.teams:
            entities.append(ExtractedEntity(name=name, entity_type=EntityType.TEAM))
        for name in self.products:
            entities.append(ExtractedEntity(name=name, entity_type=EntityType.PRODUCT))
        for name in self.locations:
            entities.append(ExtractedEntity(name=name, entity_type=EntityType.LOCATION))
        return entities

    def is_empty(self) -> bool:
        """Check if no entities were extracted."""
        return not (self.people or self.teams or self.products or self.locations)


@dataclass
class GraphNode:
    """A node in the knowledge graph."""

    node_id: str
    node_type: str  # "page" or entity type
    name: str
    metadata: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    """An edge in the knowledge graph."""

    source_id: str
    target_id: str
    relation_type: RelationType
    weight: float = 1.0
    context: str | None = None
