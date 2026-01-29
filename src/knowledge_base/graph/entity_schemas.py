"""Pydantic entity schemas for Graphiti knowledge graph.

These schemas define the structure of entities in the graph database.
They correspond to the existing EntityType enum but use Pydantic for
validation and serialization compatible with Graphiti.

Per the migration plan, these schemas are used alongside the existing
models during the gradual rollout phase.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GraphEntityType(str, Enum):
    """Types of entities that can be stored in the knowledge graph.

    This mirrors the existing EntityType enum for compatibility.
    """

    PERSON = "person"
    TEAM = "team"
    PRODUCT = "product"
    LOCATION = "location"
    TOPIC = "topic"
    DOCUMENT = "document"  # For page/chunk references


class GraphRelationType(str, Enum):
    """Types of relationships between entities in the knowledge graph.

    Extended from existing RelationType with additional Graphiti-specific relations.
    """

    # Entity mentions (page -> entity)
    MENTIONS_PERSON = "mentions_person"
    MENTIONS_TEAM = "mentions_team"
    MENTIONS_PRODUCT = "mentions_product"
    MENTIONS_LOCATION = "mentions_location"
    MENTIONS_TOPIC = "mentions_topic"

    # Authorship and ownership
    AUTHORED_BY = "authored_by"
    OWNED_BY = "owned_by"
    MAINTAINED_BY = "maintained_by"

    # Organizational relationships
    BELONGS_TO_SPACE = "belongs_to_space"
    MEMBER_OF = "member_of"
    REPORTS_TO = "reports_to"
    WORKS_ON = "works_on"

    # Content relationships
    RELATED_TO_TOPIC = "related_to_topic"
    REFERENCES = "references"
    SUPERSEDES = "supersedes"  # For versioning
    CONFLICTS_WITH = "conflicts_with"

    # Temporal relationships (Graphiti bi-temporal support)
    PRECEDED_BY = "preceded_by"
    FOLLOWED_BY = "followed_by"


class BaseGraphEntity(BaseModel):
    """Base class for all graph entities.

    Provides common fields for temporal tracking (Graphiti bi-temporal model).
    """

    name: str = Field(..., description="Primary name/identifier of the entity")
    aliases: list[str] = Field(default_factory=list, description="Alternative names/spellings")

    # Source tracking
    source_page_id: str | None = Field(None, description="Page ID where entity was extracted")
    source_chunk_id: str | None = Field(None, description="Chunk ID for precise linking")
    source_url: str | None = Field(None, description="URL of source document")

    # Temporal metadata (Graphiti bi-temporal model)
    # event_time: when the entity information was valid in the real world
    # created_at: when we learned about this entity
    event_time: datetime | None = Field(None, description="When this info was valid")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Confidence and quality
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Extraction confidence")
    verified: bool = Field(False, description="Whether entity has been verified")

    model_config = ConfigDict(use_enum_values=True)


class PersonEntity(BaseGraphEntity):
    """A person mentioned in the knowledge base.

    Examples: employees, external contacts, authors.
    """

    entity_type: GraphEntityType = Field(default=GraphEntityType.PERSON)

    # Person-specific fields
    email: str | None = Field(None, description="Email address if known")
    slack_id: str | None = Field(None, description="Slack user ID if known")
    title: str | None = Field(None, description="Job title")
    team: str | None = Field(None, description="Team name")
    department: str | None = Field(None, description="Department")


class TeamEntity(BaseGraphEntity):
    """A team, department, or organizational unit.

    Examples: Engineering, Platform Team, HR Department.
    """

    entity_type: GraphEntityType = Field(default=GraphEntityType.TEAM)

    # Team-specific fields
    slack_channel: str | None = Field(None, description="Team's Slack channel")
    confluence_space: str | None = Field(None, description="Team's Confluence space key")
    parent_team: str | None = Field(None, description="Parent team/department")
    lead: str | None = Field(None, description="Team lead name")


class ProductEntity(BaseGraphEntity):
    """A product, service, tool, or system.

    Examples: internal tools, services, external products.
    """

    entity_type: GraphEntityType = Field(default=GraphEntityType.PRODUCT)

    # Product-specific fields
    version: str | None = Field(None, description="Current version")
    status: str | None = Field(None, description="active, deprecated, beta, etc.")
    documentation_url: str | None = Field(None, description="Link to documentation")
    owner_team: str | None = Field(None, description="Team responsible for product")
    category: str | None = Field(None, description="Product category")


class LocationEntity(BaseGraphEntity):
    """A physical or virtual location.

    Examples: offices, data centers, regions, meeting rooms.
    """

    entity_type: GraphEntityType = Field(default=GraphEntityType.LOCATION)

    # Location-specific fields
    address: str | None = Field(None, description="Physical address")
    region: str | None = Field(None, description="Geographic region")
    timezone: str | None = Field(None, description="Timezone")
    location_type: str | None = Field(None, description="office, remote, datacenter, etc.")


class TopicEntity(BaseGraphEntity):
    """A topic, concept, or subject area.

    Examples: onboarding, security, API, data processing.
    """

    entity_type: GraphEntityType = Field(default=GraphEntityType.TOPIC)

    # Topic-specific fields
    parent_topic: str | None = Field(None, description="Broader topic")
    related_topics: list[str] = Field(default_factory=list, description="Related topics")
    description: str | None = Field(None, description="Brief description of topic")


class DocumentEntity(BaseGraphEntity):
    """A document or chunk in the knowledge base.

    Used to create chunk-level entity linking (not just page-level).
    """

    entity_type: GraphEntityType = Field(default=GraphEntityType.DOCUMENT)

    # Document-specific fields
    page_id: str = Field(..., description="Confluence/source page ID")
    chunk_id: str | None = Field(None, description="Specific chunk ID")
    chunk_index: int | None = Field(None, description="Chunk index within page")
    page_title: str | None = Field(None, description="Page title")
    space_key: str | None = Field(None, description="Confluence space key")
    doc_type: str | None = Field(None, description="policy, how-to, FAQ, etc.")

    # Quality tracking (synced with ChromaDB source of truth)
    quality_score: float = Field(100.0, ge=0.0, le=100.0)


class GraphRelationship(BaseModel):
    """A relationship between two entities in the graph.

    Includes temporal metadata for Graphiti's bi-temporal model.
    """

    source_id: str = Field(..., description="Source entity ID")
    target_id: str = Field(..., description="Target entity ID")
    relation_type: GraphRelationType = Field(..., description="Type of relationship")

    # Relationship metadata
    weight: float = Field(1.0, ge=0.0, description="Relationship strength/confidence")
    context: str | None = Field(None, description="Context where relationship was found")

    # Temporal metadata (Graphiti bi-temporal)
    valid_from: datetime | None = Field(None, description="When relationship became valid")
    valid_until: datetime | None = Field(None, description="When relationship ended (if known)")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(use_enum_values=True)


# Type alias for any entity type
AnyGraphEntity = PersonEntity | TeamEntity | ProductEntity | LocationEntity | TopicEntity | DocumentEntity


def entity_type_to_schema(entity_type: GraphEntityType | str) -> type[BaseGraphEntity]:
    """Get the schema class for an entity type.

    Args:
        entity_type: Entity type enum or string value

    Returns:
        Pydantic model class for the entity type
    """
    if isinstance(entity_type, str):
        entity_type = GraphEntityType(entity_type)

    mapping = {
        GraphEntityType.PERSON: PersonEntity,
        GraphEntityType.TEAM: TeamEntity,
        GraphEntityType.PRODUCT: ProductEntity,
        GraphEntityType.LOCATION: LocationEntity,
        GraphEntityType.TOPIC: TopicEntity,
        GraphEntityType.DOCUMENT: DocumentEntity,
    }

    return mapping.get(entity_type, BaseGraphEntity)


def create_entity(entity_type: GraphEntityType | str, **kwargs) -> AnyGraphEntity:
    """Create an entity instance of the appropriate type.

    Args:
        entity_type: Type of entity to create
        **kwargs: Entity fields

    Returns:
        Typed entity instance
    """
    schema_class = entity_type_to_schema(entity_type)
    return schema_class(**kwargs)
