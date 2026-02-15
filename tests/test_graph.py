"""Tests for the knowledge graph module."""

import pytest

from knowledge_base.graph.models import (
    EntityType,
    ExtractedEntities,
    ExtractedEntity,
    RelationType,
)
from knowledge_base.graph.entity_extractor import EntityResolver


class TestExtractedEntity:
    """Tests for ExtractedEntity model."""

    def test_entity_id_generation(self):
        """Test entity ID generation from name and type."""
        entity = ExtractedEntity(name="John Smith", entity_type=EntityType.PERSON)
        assert entity.entity_id == "person:john_smith"

    def test_entity_id_special_chars(self):
        """Test entity ID handles special characters."""
        entity = ExtractedEntity(name="O'Brien-Jones", entity_type=EntityType.PERSON)
        # Dashes become underscores, apostrophes removed
        assert entity.entity_id == "person:obrien_jones"

    def test_entity_id_product(self):
        """Test entity ID for product type."""
        entity = ExtractedEntity(name="Google Cloud Platform", entity_type=EntityType.PRODUCT)
        assert entity.entity_id == "product:google_cloud_platform"


class TestExtractedEntities:
    """Tests for ExtractedEntities model."""

    def test_is_empty_true(self):
        """Test is_empty returns True for empty entities."""
        entities = ExtractedEntities()
        assert entities.is_empty() is True

    def test_is_empty_false(self):
        """Test is_empty returns False when entities exist."""
        entities = ExtractedEntities(people=["John"])
        assert entities.is_empty() is False

    def test_to_entity_list(self):
        """Test conversion to entity list."""
        entities = ExtractedEntities(
            people=["Alice", "Bob"],
            teams=["Engineering"],
            products=["Snowflake"],
            locations=["Prague"],
        )
        entity_list = entities.to_entity_list()

        assert len(entity_list) == 5
        types = [e.entity_type for e in entity_list]
        assert types.count(EntityType.PERSON) == 2
        assert types.count(EntityType.TEAM) == 1
        assert types.count(EntityType.PRODUCT) == 1
        assert types.count(EntityType.LOCATION) == 1


class TestEntityResolver:
    """Tests for EntityResolver."""

    def test_add_and_resolve_alias(self):
        """Test adding and resolving aliases."""
        resolver = EntityResolver()
        resolver.add_alias("GCP", "Google Cloud Platform")

        entity = ExtractedEntity(name="GCP", entity_type=EntityType.PRODUCT)
        resolved = resolver.resolve(entity)

        assert resolved.name == "Google Cloud Platform"
        assert "GCP" in resolved.aliases

    def test_no_alias_passthrough(self):
        """Test entity without alias passes through unchanged."""
        resolver = EntityResolver()
        entity = ExtractedEntity(name="Unknown Entity", entity_type=EntityType.PRODUCT)
        resolved = resolver.resolve(entity)

        assert resolved.name == "Unknown Entity"
        assert resolved.aliases == []

    def test_resolve_all_merges(self):
        """Test resolve_all merges entities with same canonical name."""
        resolver = EntityResolver()
        resolver.add_alias("GCP", "Google Cloud Platform")

        entities = [
            ExtractedEntity(name="GCP", entity_type=EntityType.PRODUCT),
            ExtractedEntity(name="Google Cloud Platform", entity_type=EntityType.PRODUCT),
        ]
        resolved = resolver.resolve_all(entities)

        assert len(resolved) == 1
        assert resolved[0].name == "Google Cloud Platform"


class TestRelationType:
    """Tests for RelationType enum."""

    def test_relation_types_exist(self):
        """Test all expected relation types exist."""
        assert RelationType.MENTIONS_PERSON.value == "mentions_person"
        assert RelationType.MENTIONS_TEAM.value == "mentions_team"
        assert RelationType.AUTHORED_BY.value == "authored_by"
        assert RelationType.BELONGS_TO_SPACE.value == "belongs_to_space"
        assert RelationType.RELATED_TO_TOPIC.value == "related_to_topic"
