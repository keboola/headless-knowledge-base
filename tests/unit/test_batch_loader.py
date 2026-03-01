"""Tests for batch import pipeline Neo4j bulk loader."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from knowledge_base.batch.loader import Neo4jBulkLoader, _sanitize_label
from knowledge_base.batch.models import ResolvedEntity, ResolvedRelationship
from knowledge_base.vectorstore.indexer import ChunkData


# ---------------------------------------------------------------------------
# _sanitize_label tests
# ---------------------------------------------------------------------------


class TestSanitizeLabel:
    """Tests for the _sanitize_label utility function."""

    def test_simple_label(self) -> None:
        assert _sanitize_label("Technology") == "Technology"

    def test_removes_special_chars(self) -> None:
        assert _sanitize_label("My-Type!@#") == "MyType"

    def test_removes_spaces(self) -> None:
        assert _sanitize_label("Team Lead") == "TeamLead"

    def test_removes_hyphens_and_dots(self) -> None:
        assert _sanitize_label("sub-type.v2") == "Subtypev2"

    def test_empty_string_returns_entity(self) -> None:
        assert _sanitize_label("") == "Entity"

    def test_all_special_chars_returns_entity(self) -> None:
        assert _sanitize_label("!@#$%") == "Entity"

    def test_starts_with_number_prepends_x(self) -> None:
        assert _sanitize_label("123abc") == "X123abc"

    def test_uppercase_first_letter(self) -> None:
        assert _sanitize_label("person") == "Person"

    def test_keeps_underscores(self) -> None:
        assert _sanitize_label("team_lead") == "Team_lead"

    def test_alphanumeric_preserved(self) -> None:
        assert _sanitize_label("TypeA2B") == "TypeA2B"


# ---------------------------------------------------------------------------
# Helper fixtures and factories
# ---------------------------------------------------------------------------


def _make_chunk(
    chunk_id: str = "chunk-001",
    content: str = "Test content.",
    page_id: str = "page-1",
    page_title: str = "Test Page",
    space_key: str = "ENG",
    updated_at: str = "2026-03-01T12:00:00Z",
) -> ChunkData:
    return ChunkData(
        chunk_id=chunk_id,
        content=content,
        page_id=page_id,
        page_title=page_title,
        chunk_index=0,
        space_key=space_key,
        updated_at=updated_at,
    )


def _make_entity(
    uuid: str = "ent-1",
    canonical_name: str = "Platform Team",
    entity_type: str = "Team",
    summary: str = "A team.",
    name_embedding: list[float] | None = None,
    mentioned_in_episodes: list[str] | None = None,
) -> ResolvedEntity:
    return ResolvedEntity(
        uuid=uuid,
        canonical_name=canonical_name,
        entity_type=entity_type,
        summary=summary,
        name_embedding=name_embedding,
        mentioned_in_episodes=mentioned_in_episodes or [],
    )


def _make_relationship(
    uuid: str = "rel-1",
    source_entity_uuid: str = "ent-1",
    target_entity_uuid: str = "ent-2",
    relationship_name: str = "manages",
    fact: str = "Entity 1 manages Entity 2.",
    fact_embedding: list[float] | None = None,
    episode_uuids: list[str] | None = None,
) -> ResolvedRelationship:
    return ResolvedRelationship(
        uuid=uuid,
        source_entity_uuid=source_entity_uuid,
        target_entity_uuid=target_entity_uuid,
        relationship_name=relationship_name,
        fact=fact,
        fact_embedding=fact_embedding,
        episode_uuids=episode_uuids or [],
    )


@pytest.fixture
def mock_driver() -> AsyncMock:
    """Create a mock Neo4j driver."""
    driver = AsyncMock()
    driver.execute_query = AsyncMock(return_value=([], None, None))
    return driver


@pytest.fixture
def mock_graphiti_client(mock_driver: AsyncMock) -> MagicMock:
    """Create a mock GraphitiClient that returns a mock graphiti with the mock driver."""
    mock_graphiti = AsyncMock()
    mock_graphiti.driver = mock_driver

    mock_client = MagicMock()
    mock_client.get_client = AsyncMock(return_value=mock_graphiti)
    return mock_client


@pytest.fixture
def loader(mock_graphiti_client: MagicMock) -> Neo4jBulkLoader:
    """Create a Neo4jBulkLoader with mocked dependencies."""
    with patch("knowledge_base.batch.loader.settings") as mock_settings:
        mock_settings.GRAPH_GROUP_ID = "test-group"
        mock_settings.BATCH_NEO4J_WRITE_SIZE = 500

        with patch(
            "knowledge_base.batch.loader.GraphitiClient",
            return_value=mock_graphiti_client,
        ):
            return Neo4jBulkLoader(group_id="test-group", batch_size=500)


# ---------------------------------------------------------------------------
# Batch splitting tests
# ---------------------------------------------------------------------------


class TestBatchSplitting:
    """Tests for _execute_batch splitting logic."""

    @pytest.mark.asyncio
    async def test_exact_batch_size_single_call(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """500 items with batch_size=500 -> 1 execute_query call."""
        data = [{"uuid": f"item-{i}"} for i in range(500)]
        await loader._execute_batch("UNWIND $batch AS x RETURN x", data, "items")

        assert mock_driver.execute_query.call_count == 1
        batch_arg = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_arg) == 500

    @pytest.mark.asyncio
    async def test_multiple_batches(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """1500 items with batch_size=500 -> 3 execute_query calls."""
        data = [{"uuid": f"item-{i}"} for i in range(1500)]
        await loader._execute_batch("UNWIND $batch AS x RETURN x", data, "items")

        assert mock_driver.execute_query.call_count == 3

    @pytest.mark.asyncio
    async def test_partial_last_batch(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """750 items with batch_size=500 -> 2 calls (500 + 250)."""
        data = [{"uuid": f"item-{i}"} for i in range(750)]
        await loader._execute_batch("UNWIND $batch AS x RETURN x", data, "items")

        assert mock_driver.execute_query.call_count == 2
        # First batch: 500 items
        first_batch = mock_driver.execute_query.call_args_list[0][1]["params"]["batch"]
        assert len(first_batch) == 500
        # Second batch: 250 items
        second_batch = mock_driver.execute_query.call_args_list[1][1]["params"]["batch"]
        assert len(second_batch) == 250

    @pytest.mark.asyncio
    async def test_empty_data_no_calls(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Empty data list -> no execute_query calls."""
        await loader._execute_batch("UNWIND $batch AS x RETURN x", [], "items")
        mock_driver.execute_query.assert_not_called()


# ---------------------------------------------------------------------------
# load_episodes tests
# ---------------------------------------------------------------------------


class TestLoadEpisodes:
    """Tests for load_episodes Cypher query and data."""

    @pytest.mark.asyncio
    async def test_creates_episodic_nodes(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """load_episodes creates Episodic nodes with correct properties."""
        chunks = [_make_chunk(chunk_id="chunk-1")]
        episode_uuids = {"chunk-1": "ep-uuid-1"}

        await loader.load_episodes(chunks, episode_uuids)

        assert mock_driver.execute_query.call_count == 1
        query = mock_driver.execute_query.call_args[0][0]
        assert "Episodic" in query
        assert "MERGE" in query
        assert "UNWIND" in query

    @pytest.mark.asyncio
    async def test_source_description_is_json(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """source_description field is JSON-serialized metadata."""
        chunk = _make_chunk(
            chunk_id="chunk-1",
            page_title="My Page",
            space_key="ENG",
        )
        episode_uuids = {"chunk-1": "ep-uuid-1"}

        await loader.load_episodes([chunk], episode_uuids)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        source_desc = batch_data[0]["source_description"]

        # Must be valid JSON
        parsed = json.loads(source_desc)
        assert parsed["page_title"] == "My Page"
        assert parsed["space_key"] == "ENG"

    @pytest.mark.asyncio
    async def test_skips_chunks_without_episode_uuid(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Chunks not in episode_uuids mapping are skipped."""
        chunks = [
            _make_chunk(chunk_id="chunk-1"),
            _make_chunk(chunk_id="chunk-2"),
        ]
        episode_uuids = {"chunk-1": "ep-1"}  # chunk-2 missing

        await loader.load_episodes(chunks, episode_uuids)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["uuid"] == "ep-1"


# ---------------------------------------------------------------------------
# load_entities tests
# ---------------------------------------------------------------------------


class TestLoadEntities:
    """Tests for load_entities Cypher query and data."""

    @pytest.mark.asyncio
    async def test_entity_query_has_dynamic_label(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Entity nodes get a dynamic sub-label based on entity_type."""
        entities = [_make_entity(entity_type="Technology")]

        await loader.load_entities(entities)

        query = mock_driver.execute_query.call_args[0][0]
        assert "Entity:Technology" in query
        assert "MERGE" in query

    @pytest.mark.asyncio
    async def test_entities_grouped_by_type(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Entities of different types produce separate UNWIND queries."""
        entities = [
            _make_entity(uuid="ent-1", entity_type="Person"),
            _make_entity(uuid="ent-2", entity_type="Team"),
            _make_entity(uuid="ent-3", entity_type="Person"),
        ]

        await loader.load_entities(entities)

        # Two different types -> 2 execute_query calls
        assert mock_driver.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_entity_data_has_correct_fields(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Entity batch rows contain all expected fields."""
        embedding = [0.1, 0.2, 0.3]
        entities = [
            _make_entity(
                uuid="ent-1",
                canonical_name="Alice",
                entity_type="Person",
                summary="An engineer.",
                name_embedding=embedding,
            )
        ]

        await loader.load_entities(entities)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        row = batch_data[0]
        assert row["uuid"] == "ent-1"
        assert row["name"] == "Alice"
        assert row["group_id"] == "test-group"
        assert row["name_embedding"] == embedding
        assert row["summary"] == "An engineer."

    @pytest.mark.asyncio
    async def test_entity_without_embedding_uses_empty_list(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Entities without embeddings get an empty list (not None)."""
        entities = [_make_entity(name_embedding=None)]

        await loader.load_entities(entities)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert batch_data[0]["name_embedding"] == []


# ---------------------------------------------------------------------------
# load_relationships tests
# ---------------------------------------------------------------------------


class TestLoadRelationships:
    """Tests for load_relationships Cypher query and data."""

    @pytest.mark.asyncio
    async def test_relationship_query_structure(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Relationship query creates RELATES_TO edges between Entity nodes."""
        rels = [_make_relationship()]

        await loader.load_relationships(rels)

        query = mock_driver.execute_query.call_args[0][0]
        assert "RELATES_TO" in query
        assert "MATCH (src:Entity" in query
        assert "MATCH (tgt:Entity" in query
        assert "MERGE" in query

    @pytest.mark.asyncio
    async def test_relationship_data_has_correct_fields(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Relationship batch rows contain all expected fields."""
        embedding = [0.5, 0.6]
        rels = [
            _make_relationship(
                uuid="rel-1",
                source_entity_uuid="ent-1",
                target_entity_uuid="ent-2",
                relationship_name="manages",
                fact="A manages B.",
                fact_embedding=embedding,
                episode_uuids=["ep-1", "ep-2"],
            )
        ]

        await loader.load_relationships(rels)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        row = batch_data[0]
        assert row["uuid"] == "rel-1"
        assert row["source_uuid"] == "ent-1"
        assert row["target_uuid"] == "ent-2"
        assert row["name"] == "manages"
        assert row["fact"] == "A manages B."
        assert row["fact_embedding"] == embedding
        assert row["episodes"] == ["ep-1", "ep-2"]
        assert row["group_id"] == "test-group"


# ---------------------------------------------------------------------------
# load_mentions tests
# ---------------------------------------------------------------------------


class TestLoadMentions:
    """Tests for load_mentions Cypher query and data."""

    @pytest.mark.asyncio
    async def test_mentions_query_structure(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Mentions query creates MENTIONS edges from Episodic to Entity."""
        entities = [
            _make_entity(
                uuid="ent-1",
                mentioned_in_episodes=["ep-1"],
            )
        ]
        await loader.load_mentions(entities, ["ep-1"])

        query = mock_driver.execute_query.call_args[0][0]
        assert "MENTIONS" in query
        assert "Episodic" in query
        assert "Entity" in query

    @pytest.mark.asyncio
    async def test_mentions_skips_unknown_episodes(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Mention edges referencing episodes not in episode_uuids_all are skipped."""
        entities = [
            _make_entity(
                uuid="ent-1",
                mentioned_in_episodes=["ep-1", "ep-unknown"],
            )
        ]

        await loader.load_mentions(entities, ["ep-1"])

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        # Only ep-1 should be in the batch
        episode_uuids_in_batch = [row["episode_uuid"] for row in batch_data]
        assert "ep-1" in episode_uuids_in_batch
        assert "ep-unknown" not in episode_uuids_in_batch

    @pytest.mark.asyncio
    async def test_mentions_multiple_entities_multiple_episodes(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Multiple entities with multiple episodes produce correct mention count."""
        entities = [
            _make_entity(uuid="ent-1", mentioned_in_episodes=["ep-1", "ep-2"]),
            _make_entity(uuid="ent-2", mentioned_in_episodes=["ep-2"]),
        ]

        await loader.load_mentions(entities, ["ep-1", "ep-2"])

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 3  # ent-1:ep-1, ent-1:ep-2, ent-2:ep-2


# ---------------------------------------------------------------------------
# update_episode_edge_refs tests
# ---------------------------------------------------------------------------


class TestUpdateEpisodeEdgeRefs:
    """Tests for update_episode_edge_refs."""

    @pytest.mark.asyncio
    async def test_episode_edge_refs_populated(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Episodes get entity_edges list populated from relationships."""
        chunks = [_make_chunk(chunk_id="chunk-1")]
        episode_uuids = {"chunk-1": "ep-1"}
        relationships = [
            _make_relationship(uuid="rel-1", episode_uuids=["ep-1"]),
            _make_relationship(uuid="rel-2", episode_uuids=["ep-1"]),
        ]

        await loader.update_episode_edge_refs(chunks, episode_uuids, relationships)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert set(batch_data[0]["edge_uuids"]) == {"rel-1", "rel-2"}

    @pytest.mark.asyncio
    async def test_episode_with_no_relationships(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """Episodes with no relationships get an empty entity_edges list."""
        chunks = [_make_chunk(chunk_id="chunk-1")]
        episode_uuids = {"chunk-1": "ep-1"}
        relationships = []  # no relationships

        await loader.update_episode_edge_refs(chunks, episode_uuids, relationships)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert batch_data[0]["edge_uuids"] == []


# ---------------------------------------------------------------------------
# clear_graph tests
# ---------------------------------------------------------------------------


class TestClearGraph:
    """Tests for clear_graph."""

    @pytest.mark.asyncio
    async def test_clear_graph_deletes_in_batches(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """clear_graph repeatedly deletes until nothing remains."""
        # First call: delete 500 nodes; second call: 0 (done)
        mock_driver.execute_query.side_effect = [
            ([{"deleted": 500}], None, None),
            ([{"deleted": 0}], None, None),
        ]

        total = await loader.clear_graph()

        assert total == 500
        assert mock_driver.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_clear_graph_empty(
        self, loader: Neo4jBulkLoader, mock_driver: AsyncMock
    ) -> None:
        """clear_graph on empty graph returns 0."""
        mock_driver.execute_query.return_value = ([{"deleted": 0}], None, None)

        total = await loader.clear_graph()

        assert total == 0
