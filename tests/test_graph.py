"""Tests for the knowledge graph module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import networkx as nx

from knowledge_base.graph.models import (
    EntityType,
    ExtractedEntities,
    ExtractedEntity,
    RelationType,
)
from knowledge_base.graph.entity_extractor import EntityExtractor, EntityResolver
from knowledge_base.graph.graph_retriever import GraphRetriever


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


class TestEntityExtractor:
    """Tests for EntityExtractor."""

    @pytest.mark.asyncio
    async def test_extract_empty_content(self):
        """Test extraction from empty content returns empty."""
        mock_llm = MagicMock()
        extractor = EntityExtractor(mock_llm)

        result = await extractor.extract("")
        assert result.is_empty()

    @pytest.mark.asyncio
    async def test_extract_with_mock_llm(self):
        """Test extraction with mocked LLM response."""
        mock_llm = MagicMock()
        mock_llm.generate_json = AsyncMock(return_value={
            "people": ["Alice Smith", "Bob Jones"],
            "teams": ["Engineering"],
            "products": ["Snowflake", "GCP"],
            "locations": ["Prague office"],
        })

        extractor = EntityExtractor(mock_llm)
        result = await extractor.extract("Sample document content")

        assert len(result.people) == 2
        assert "Alice Smith" in result.people
        assert len(result.teams) == 1
        assert len(result.products) == 2
        assert len(result.locations) == 1

    @pytest.mark.asyncio
    async def test_extract_handles_llm_error(self):
        """Test extraction handles LLM errors gracefully."""
        mock_llm = MagicMock()
        mock_llm.generate_json = AsyncMock(side_effect=Exception("LLM error"))

        extractor = EntityExtractor(mock_llm)
        result = await extractor.extract("Sample content")

        assert result.is_empty()

    @pytest.mark.asyncio
    async def test_extract_deduplicates(self):
        """Test extraction deduplicates entities."""
        mock_llm = MagicMock()
        mock_llm.generate_json = AsyncMock(return_value={
            "people": ["John Smith", "john smith", "JOHN SMITH"],
            "teams": [],
            "products": [],
            "locations": [],
        })

        extractor = EntityExtractor(mock_llm)
        result = await extractor.extract("Sample content")

        assert len(result.people) == 1

    @pytest.mark.asyncio
    async def test_extract_batch(self):
        """Test batch extraction."""
        mock_llm = MagicMock()
        mock_llm.generate_json = AsyncMock(return_value={
            "people": ["Person A"],
            "teams": [],
            "products": [],
            "locations": [],
        })

        extractor = EntityExtractor(mock_llm)
        docs = [
            {"page_id": "page1", "content": "Content 1"},
            {"page_id": "page2", "content": "Content 2"},
        ]
        results = await extractor.extract_batch(docs)

        assert len(results) == 2
        assert "page1" in results
        assert "page2" in results


class TestGraphRetriever:
    """Tests for GraphRetriever."""

    def setup_method(self):
        """Set up test graph."""
        self.graph = nx.DiGraph()

        # Add page nodes
        self.graph.add_node("page:page1", node_type="page", name="Doc 1")
        self.graph.add_node("page:page2", node_type="page", name="Doc 2")
        self.graph.add_node("page:page3", node_type="page", name="Doc 3")

        # Add entity nodes
        self.graph.add_node("person:john_smith", node_type="person", name="John Smith", aliases=[])
        self.graph.add_node("team:engineering", node_type="team", name="Engineering", aliases=["eng"])
        self.graph.add_node("product:snowflake", node_type="product", name="Snowflake", aliases=[])

        # Add edges: page1 -> john_smith, engineering
        self.graph.add_edge("page:page1", "person:john_smith", relation_type="mentions_person", weight=1.0)
        self.graph.add_edge("page:page1", "team:engineering", relation_type="mentions_team", weight=1.5)

        # Add edges: page2 -> john_smith, snowflake
        self.graph.add_edge("page:page2", "person:john_smith", relation_type="mentions_person", weight=1.0)
        self.graph.add_edge("page:page2", "product:snowflake", relation_type="mentions_product", weight=1.0)

        # Add edges: page3 -> engineering
        self.graph.add_edge("page:page3", "team:engineering", relation_type="mentions_team", weight=1.0)

    def test_get_related_documents(self):
        """Test finding related documents via graph traversal."""
        retriever = GraphRetriever(self.graph)

        # page1 is connected to page2 via john_smith
        # page1 is connected to page3 via engineering
        related = retriever.get_related_documents("page1", hops=2)

        assert "page2" in related
        assert "page3" in related
        assert "page1" not in related

    def test_get_related_documents_not_in_graph(self):
        """Test handling of document not in graph."""
        retriever = GraphRetriever(self.graph)
        related = retriever.get_related_documents("nonexistent", hops=2)
        assert related == []

    def test_find_by_entity(self):
        """Test finding documents by entity name."""
        retriever = GraphRetriever(self.graph)

        pages = retriever.find_by_entity("John Smith")
        assert "page1" in pages
        assert "page2" in pages
        assert "page3" not in pages

    def test_find_by_entity_with_type(self):
        """Test finding documents by entity name and type."""
        retriever = GraphRetriever(self.graph)

        pages = retriever.find_by_entity("Engineering", "team")
        assert "page1" in pages
        assert "page3" in pages

    def test_find_by_entity_alias(self):
        """Test finding documents by entity alias."""
        retriever = GraphRetriever(self.graph)

        # "eng" is an alias for "Engineering"
        pages = retriever.find_by_entity("eng")
        assert "page1" in pages
        assert "page3" in pages

    def test_get_document_entities(self):
        """Test getting all entities for a document."""
        retriever = GraphRetriever(self.graph)

        entities = retriever.get_document_entities("page1")
        entity_names = [e["name"] for e in entities]

        assert "John Smith" in entity_names
        assert "Engineering" in entity_names
        assert len(entities) == 2

    def test_get_common_entities(self):
        """Test finding common entities across documents."""
        retriever = GraphRetriever(self.graph)

        common = retriever.get_common_entities(["page1", "page2"])

        # john_smith is common to both
        entity_ids = [e["entity_id"] for e in common]
        assert "person:john_smith" in entity_ids

    def test_expand_query_with_entities(self):
        """Test query expansion through common entities."""
        retriever = GraphRetriever(self.graph)

        # Start with page1, should find page2 and page3 through shared entities
        additional = retriever.expand_query_with_entities("test query", ["page1"], top_k=5)

        # page2 shares john_smith, page3 shares engineering
        assert len(additional) <= 5


class TestRelationType:
    """Tests for RelationType enum."""

    def test_relation_types_exist(self):
        """Test all expected relation types exist."""
        assert RelationType.MENTIONS_PERSON.value == "mentions_person"
        assert RelationType.MENTIONS_TEAM.value == "mentions_team"
        assert RelationType.AUTHORED_BY.value == "authored_by"
        assert RelationType.BELONGS_TO_SPACE.value == "belongs_to_space"
        assert RelationType.RELATED_TO_TOPIC.value == "related_to_topic"
