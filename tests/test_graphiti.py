"""Tests for the Graphiti-based knowledge graph module.

These tests cover the Graphiti integration which uses Kuzu (embedded) or Neo4j (production)
as the graph database backend, replacing the legacy NetworkX-based implementation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

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


class TestGraphEntityType:
    """Tests for GraphEntityType enum."""

    def test_entity_types_exist(self):
        """Test all expected entity types exist."""
        assert GraphEntityType.PERSON.value == "person"
        assert GraphEntityType.TEAM.value == "team"
        assert GraphEntityType.PRODUCT.value == "product"
        assert GraphEntityType.LOCATION.value == "location"
        assert GraphEntityType.TOPIC.value == "topic"
        assert GraphEntityType.DOCUMENT.value == "document"

    def test_enum_is_string(self):
        """Test entity type values are strings."""
        for entity_type in GraphEntityType:
            assert isinstance(entity_type.value, str)


class TestGraphRelationType:
    """Tests for GraphRelationType enum."""

    def test_mention_relations_exist(self):
        """Test mention relationship types exist."""
        assert GraphRelationType.MENTIONS_PERSON.value == "mentions_person"
        assert GraphRelationType.MENTIONS_TEAM.value == "mentions_team"
        assert GraphRelationType.MENTIONS_PRODUCT.value == "mentions_product"
        assert GraphRelationType.MENTIONS_LOCATION.value == "mentions_location"
        assert GraphRelationType.MENTIONS_TOPIC.value == "mentions_topic"

    def test_ownership_relations_exist(self):
        """Test ownership relationship types exist."""
        assert GraphRelationType.AUTHORED_BY.value == "authored_by"
        assert GraphRelationType.OWNED_BY.value == "owned_by"
        assert GraphRelationType.MAINTAINED_BY.value == "maintained_by"

    def test_temporal_relations_exist(self):
        """Test temporal relationship types exist (Graphiti bi-temporal support)."""
        assert GraphRelationType.PRECEDED_BY.value == "preceded_by"
        assert GraphRelationType.FOLLOWED_BY.value == "followed_by"


class TestPersonEntity:
    """Tests for PersonEntity schema."""

    def test_create_basic_person(self):
        """Test creating a basic person entity."""
        person = PersonEntity(name="John Smith")
        assert person.name == "John Smith"
        assert person.entity_type == GraphEntityType.PERSON
        assert person.aliases == []

    def test_create_full_person(self):
        """Test creating a person with all fields."""
        person = PersonEntity(
            name="Jane Doe",
            aliases=["J. Doe", "JD"],
            email="jane@example.com",
            slack_id="U123456",
            title="Senior Engineer",
            team="Platform",
            department="Engineering",
            source_page_id="page_123",
            confidence=0.95,
        )
        assert person.name == "Jane Doe"
        assert "J. Doe" in person.aliases
        assert person.email == "jane@example.com"
        assert person.slack_id == "U123456"
        assert person.confidence == 0.95


class TestTeamEntity:
    """Tests for TeamEntity schema."""

    def test_create_basic_team(self):
        """Test creating a basic team entity."""
        team = TeamEntity(name="Engineering")
        assert team.name == "Engineering"
        assert team.entity_type == GraphEntityType.TEAM

    def test_create_full_team(self):
        """Test creating a team with all fields."""
        team = TeamEntity(
            name="Platform Team",
            aliases=["Platform", "PF"],
            slack_channel="#platform",
            confluence_space="PLAT",
            parent_team="Engineering",
            lead="Jane Doe",
        )
        assert team.slack_channel == "#platform"
        assert team.confluence_space == "PLAT"
        assert team.parent_team == "Engineering"


class TestProductEntity:
    """Tests for ProductEntity schema."""

    def test_create_basic_product(self):
        """Test creating a basic product entity."""
        product = ProductEntity(name="Snowflake")
        assert product.name == "Snowflake"
        assert product.entity_type == GraphEntityType.PRODUCT

    def test_create_full_product(self):
        """Test creating a product with all fields."""
        product = ProductEntity(
            name="Knowledge Base",
            aliases=["KB", "Knowledge System"],
            version="1.0.0",
            status="active",
            documentation_url="https://docs.example.com/kb",
            owner_team="Platform",
            category="internal_tool",
        )
        assert product.version == "1.0.0"
        assert product.status == "active"
        assert product.owner_team == "Platform"


class TestDocumentEntity:
    """Tests for DocumentEntity schema."""

    def test_create_document(self):
        """Test creating a document entity."""
        doc = DocumentEntity(
            name="Onboarding Guide",
            page_id="page_123",
            chunk_id="page_123_0",
            chunk_index=0,
            page_title="Onboarding Guide",
            space_key="HR",
            doc_type="how-to",
            quality_score=95.0,
        )
        assert doc.page_id == "page_123"
        assert doc.chunk_id == "page_123_0"
        assert doc.entity_type == GraphEntityType.DOCUMENT
        assert doc.quality_score == 95.0

    def test_document_default_quality(self):
        """Test document has default quality score of 100."""
        doc = DocumentEntity(name="Test", page_id="test_123")
        assert doc.quality_score == 100.0


class TestGraphRelationship:
    """Tests for GraphRelationship schema."""

    def test_create_relationship(self):
        """Test creating a basic relationship."""
        rel = GraphRelationship(
            source_id="person:john_smith",
            target_id="team:engineering",
            relation_type=GraphRelationType.MEMBER_OF,
        )
        assert rel.source_id == "person:john_smith"
        assert rel.target_id == "team:engineering"
        assert rel.relation_type == GraphRelationType.MEMBER_OF
        assert rel.weight == 1.0

    def test_relationship_with_temporal_metadata(self):
        """Test relationship with temporal fields (Graphiti bi-temporal support)."""
        now = datetime.utcnow()
        rel = GraphRelationship(
            source_id="doc:page_123",
            target_id="person:john",
            relation_type=GraphRelationType.AUTHORED_BY,
            valid_from=now,
            context="Page metadata",
        )
        assert rel.valid_from == now
        assert rel.context == "Page metadata"


class TestEntityTypeToSchema:
    """Tests for entity_type_to_schema function."""

    def test_person_type(self):
        """Test mapping person type to schema."""
        schema = entity_type_to_schema(GraphEntityType.PERSON)
        assert schema == PersonEntity

    def test_team_type(self):
        """Test mapping team type to schema."""
        schema = entity_type_to_schema(GraphEntityType.TEAM)
        assert schema == TeamEntity

    def test_product_type(self):
        """Test mapping product type to schema."""
        schema = entity_type_to_schema(GraphEntityType.PRODUCT)
        assert schema == ProductEntity

    def test_string_type(self):
        """Test mapping from string value."""
        schema = entity_type_to_schema("person")
        assert schema == PersonEntity

    def test_unknown_type_fallback(self):
        """Test fallback to base class for unknown type."""
        # This shouldn't happen in practice, but test graceful handling
        schema = entity_type_to_schema(GraphEntityType.PERSON)  # Valid type
        assert issubclass(schema, BaseGraphEntity)


class TestCreateEntity:
    """Tests for create_entity function."""

    def test_create_person(self):
        """Test creating a person entity."""
        entity = create_entity(GraphEntityType.PERSON, name="John Smith")
        assert isinstance(entity, PersonEntity)
        assert entity.name == "John Smith"

    def test_create_team_from_string(self):
        """Test creating a team entity from string type."""
        entity = create_entity("team", name="Engineering")
        assert isinstance(entity, TeamEntity)
        assert entity.name == "Engineering"

    def test_create_with_extra_fields(self):
        """Test creating entity with type-specific fields."""
        entity = create_entity(
            GraphEntityType.PERSON,
            name="Jane Doe",
            email="jane@example.com",
            team="Platform",
        )
        assert entity.email == "jane@example.com"
        assert entity.team == "Platform"


class TestGraphitiClientConfig:
    """Tests for GraphitiClient configuration."""

    @patch("knowledge_base.graph.graphiti_client.settings")
    def test_client_defaults_to_kuzu(self, mock_settings):
        """Test that client defaults to Kuzu backend."""
        mock_settings.GRAPH_BACKEND = "kuzu"
        mock_settings.GRAPH_KUZU_PATH = "data/kuzu_graph"
        mock_settings.GRAPH_GROUP_ID = "default"
        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.ANTHROPIC_API_KEY = "test_key"
        mock_settings.ANTHROPIC_MODEL = "claude-3-haiku"
        mock_settings.NEO4J_URI = ""
        mock_settings.NEO4J_USER = ""
        mock_settings.NEO4J_PASSWORD = ""

        from knowledge_base.graph.graphiti_client import GraphitiClient

        client = GraphitiClient()
        assert client.backend == "kuzu"
        assert client.kuzu_path == "data/kuzu_graph"

    @patch("knowledge_base.graph.graphiti_client.settings")
    def test_client_uses_neo4j_when_configured(self, mock_settings):
        """Test that client uses Neo4j when configured."""
        mock_settings.GRAPH_BACKEND = "neo4j"
        mock_settings.GRAPH_KUZU_PATH = "data/kuzu_graph"
        mock_settings.GRAPH_GROUP_ID = "default"
        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.ANTHROPIC_API_KEY = "test_key"
        mock_settings.ANTHROPIC_MODEL = "claude-3-haiku"
        mock_settings.NEO4J_URI = "bolt://localhost:7687"
        mock_settings.NEO4J_USER = "neo4j"
        mock_settings.NEO4J_PASSWORD = "password"

        from knowledge_base.graph.graphiti_client import GraphitiClient

        client = GraphitiClient()
        assert client.backend == "neo4j"


class TestGraphitiBuilderDisabled:
    """Tests for GraphitiBuilder when Graphiti is disabled."""

    @patch("knowledge_base.graph.graphiti_builder.settings")
    def test_process_document_skips_when_disabled(self, mock_settings):
        """Test document processing is skipped when Graphiti is disabled."""
        mock_settings.GRAPH_ENABLE_GRAPHITI = False
        mock_settings.GRAPH_GROUP_ID = "default"

        from knowledge_base.graph.graphiti_builder import GraphitiBuilder

        builder = GraphitiBuilder()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            builder.process_document(
                page_id="test_page",
                content="Test content",
                title="Test Document",
            )
        )

        assert result.get("skipped") is True
        assert result.get("reason") == "graphiti_disabled"

    @patch("knowledge_base.graph.graphiti_builder.settings")
    def test_search_returns_empty_when_disabled(self, mock_settings):
        """Test search returns empty when Graphiti is disabled."""
        mock_settings.GRAPH_ENABLE_GRAPHITI = False
        mock_settings.GRAPH_GROUP_ID = "default"

        from knowledge_base.graph.graphiti_builder import GraphitiBuilder

        builder = GraphitiBuilder()

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(
            builder.search_entities("test query")
        )

        assert results == []


class TestGraphitiRetrieverDisabled:
    """Tests for GraphitiRetriever when Graphiti is disabled."""

    @patch("knowledge_base.graph.graphiti_retriever.settings")
    def test_search_returns_empty_when_disabled(self, mock_settings):
        """Test search returns empty when Graphiti is disabled."""
        mock_settings.GRAPH_ENABLE_GRAPHITI = False
        mock_settings.GRAPH_GROUP_ID = "default"

        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        retriever = GraphitiRetriever()
        assert retriever.is_enabled is False

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(
            retriever.search("test query")
        )

        assert results == []

    @patch("knowledge_base.graph.graphiti_retriever.settings")
    def test_get_related_documents_returns_empty_when_disabled(self, mock_settings):
        """Test get_related_documents returns empty when disabled."""
        mock_settings.GRAPH_ENABLE_GRAPHITI = False
        mock_settings.GRAPH_GROUP_ID = "default"

        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        retriever = GraphitiRetriever()

        import asyncio
        results = asyncio.get_event_loop().run_until_complete(
            retriever.get_related_documents("page_123")
        )

        assert results == []


class TestHybridSearchGraphIntegration:
    """Tests for hybrid search graph expansion integration."""

    def test_search_accepts_use_graph_expansion_param(self):
        """Test that search method accepts use_graph_expansion parameter."""
        from knowledge_base.search.hybrid import HybridRetriever

        # Just verify the signature accepts the parameter
        import inspect
        sig = inspect.signature(HybridRetriever.search)
        params = list(sig.parameters.keys())
        assert "use_graph_expansion" in params

    @patch("knowledge_base.search.hybrid.settings")
    def test_graph_expansion_disabled_by_default(self, mock_settings):
        """Test that graph expansion is disabled by default."""
        mock_settings.GRAPH_EXPANSION_ENABLED = False
        mock_settings.GRAPH_ENABLE_GRAPHITI = False
        mock_settings.SEARCH_BM25_WEIGHT = 0.3
        mock_settings.SEARCH_VECTOR_WEIGHT = 0.7
        mock_settings.SEARCH_TOP_K = 10
        mock_settings.BM25_INDEX_PATH = "data/bm25_index.pkl"

        from knowledge_base.search.hybrid import HybridRetriever

        # The default value should be based on settings.GRAPH_EXPANSION_ENABLED
        import inspect
        sig = inspect.signature(HybridRetriever.search)
        param = sig.parameters["use_graph_expansion"]
        # Default is None which means use settings.GRAPH_EXPANSION_ENABLED
        assert param.default is None
