"""Tests for data quality validation across resolver, loader, and vector_indices."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.batch.models import (
    ChunkExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    ResolvedEntity,
    ResolvedRelationship,
)
from knowledge_base.batch.resolver import EntityResolver, _EntityGroup
from knowledge_base.graph.vector_indices import verify_data_quality


# ---------------------------------------------------------------------------
# Helper factories (match patterns in test_batch_resolver / test_batch_loader)
# ---------------------------------------------------------------------------


def _make_extraction(
    entities: list[tuple[str, str, str]],
    relationships: list[tuple[str, str, str, str]] | None = None,
    summary: str = "Test summary.",
) -> ChunkExtractionResult:
    """Build a ChunkExtractionResult from simple tuples.

    entities: list of (name, entity_type, summary)
    relationships: list of (source, target, rel_name, fact)
    """
    return ChunkExtractionResult(
        entities=[
            ExtractedEntity(name=n, entity_type=t, summary=s)
            for n, t, s in entities
        ],
        relationships=[
            ExtractedRelationship(
                source_entity=src,
                target_entity=tgt,
                relationship_name=rn,
                fact=f,
            )
            for src, tgt, rn, f in (relationships or [])
        ],
        summary=summary,
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


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def resolver():
    """Create an EntityResolver with default similarity threshold."""
    with patch("knowledge_base.batch.resolver.settings") as mock_settings:
        mock_settings.BATCH_ENTITY_SIMILARITY_THRESHOLD = 0.85
        mock_settings.BATCH_ENTITY_FUZZY_MERGE_ENABLED = False
        yield EntityResolver()


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
def loader(mock_graphiti_client: MagicMock):
    """Create a Neo4jBulkLoader with mocked dependencies."""
    from knowledge_base.batch.loader import Neo4jBulkLoader

    with patch("knowledge_base.batch.loader.settings") as mock_settings:
        mock_settings.GRAPH_GROUP_ID = "test-group"
        mock_settings.BATCH_NEO4J_WRITE_SIZE = 500

        with patch(
            "knowledge_base.batch.loader.GraphitiClient",
            return_value=mock_graphiti_client,
        ):
            return Neo4jBulkLoader(group_id="test-group", batch_size=500)


# ---------------------------------------------------------------------------
# 1. Resolver filtering: _build_registry filters empty canonical names
# ---------------------------------------------------------------------------


class TestResolverEmptyNameFiltering:
    """Test that _build_registry filters out entities with empty canonical names."""

    @pytest.mark.asyncio
    async def test_empty_name_entity_filtered(self, resolver: EntityResolver) -> None:
        """Entities where all raw name variants are empty/whitespace are filtered out."""
        extractions = {
            "chunk-1": _make_extraction([
                ("", "Team", "A team with empty name."),
                ("Alice", "Person", "An engineer."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        entities, _ = await resolver.resolve(extractions, episode_uuids)

        # Only Alice should remain; the empty-name entity is filtered
        assert len(entities) == 1
        assert entities[0].canonical_name == "Alice"

    @pytest.mark.asyncio
    async def test_whitespace_only_name_filtered(self, resolver: EntityResolver) -> None:
        """Entities where canonical name is only whitespace are filtered out."""
        extractions = {
            "chunk-1": _make_extraction([
                ("   ", "Team", "Name is just spaces."),
                ("Bob", "Person", "A manager."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        entities, _ = await resolver.resolve(extractions, episode_uuids)

        assert len(entities) == 1
        assert entities[0].canonical_name == "Bob"

    @pytest.mark.asyncio
    async def test_empty_name_filter_logs_warning(
        self, resolver: EntityResolver, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Filtering empty-name entities logs a warning with the count."""
        extractions = {
            "chunk-1": _make_extraction([
                ("", "Team", "Empty."),
                ("  ", "Person", "Whitespace."),
                ("Charlie", "Person", "Valid."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        with caplog.at_level(logging.WARNING, logger="knowledge_base.batch.resolver"):
            entities, _ = await resolver.resolve(extractions, episode_uuids)

        assert len(entities) == 1
        # Check that a warning about filtered entities was logged
        filtered_warnings = [
            r for r in caplog.records
            if "empty canonical names" in r.message.lower()
        ]
        assert len(filtered_warnings) >= 1

    def test_build_registry_directly_with_empty_group(
        self, resolver: EntityResolver
    ) -> None:
        """Calling _build_registry with an EntityGroup that yields an empty canonical name."""
        group = _EntityGroup(normalized_name="", entity_type="team")
        group.raw_names.add("")
        group.summaries.append("Some summary.")

        valid_group = _EntityGroup(normalized_name="alice", entity_type="person")
        valid_group.raw_names.add("Alice")
        valid_group.summaries.append("An engineer.")

        entity_groups = {
            ("", "team"): group,
            ("alice", "person"): valid_group,
        }

        resolved, registry = resolver._build_registry(entity_groups)

        # Only Alice should be in the resolved list
        assert len(resolved) == 1
        assert resolved[0].canonical_name == "Alice"

    @pytest.mark.asyncio
    async def test_valid_entities_pass_through(self, resolver: EntityResolver) -> None:
        """All valid entities are preserved after filtering."""
        extractions = {
            "chunk-1": _make_extraction([
                ("Alice", "Person", "Engineer."),
                ("Bob", "Person", "Manager."),
                ("Platform Team", "Team", "A team."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        entities, _ = await resolver.resolve(extractions, episode_uuids)

        assert len(entities) == 3
        names = {e.canonical_name for e in entities}
        assert "Alice" in names
        assert "Bob" in names
        assert "Platform Team" in names


# ---------------------------------------------------------------------------
# 2. Loader entity validation: load_entities skips bad entities
# ---------------------------------------------------------------------------


class TestLoaderEntityValidation:
    """Test that load_entities validates entities before writing to Neo4j."""

    @pytest.mark.asyncio
    async def test_skips_entity_with_empty_name(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """Entities with empty canonical_name are skipped."""
        entities = [
            _make_entity(uuid="ent-1", canonical_name=""),
            _make_entity(uuid="ent-2", canonical_name="Alice", entity_type="Person"),
        ]

        await loader.load_entities(entities)

        # Only Alice should be written
        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_skips_entity_with_whitespace_only_name(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """Entities with whitespace-only canonical_name are skipped."""
        entities = [
            _make_entity(uuid="ent-1", canonical_name="   "),
            _make_entity(uuid="ent-2", canonical_name="Bob", entity_type="Person"),
        ]

        await loader.load_entities(entities)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_skips_entity_with_wrong_embedding_dimensions(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """Entities with embedding dim != 768 are skipped."""
        wrong_dim_embedding = [0.1] * 256  # 256 instead of 768
        correct_dim_embedding = [0.1] * 768

        entities = [
            _make_entity(
                uuid="ent-bad",
                canonical_name="BadEmbed",
                entity_type="Person",
                name_embedding=wrong_dim_embedding,
            ),
            _make_entity(
                uuid="ent-good",
                canonical_name="GoodEmbed",
                entity_type="Person",
                name_embedding=correct_dim_embedding,
            ),
        ]

        await loader.load_entities(entities)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["uuid"] == "ent-good"

    @pytest.mark.asyncio
    async def test_entity_without_embedding_passes(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """Entities with no embedding (None) are valid and pass through."""
        entities = [
            _make_entity(uuid="ent-1", canonical_name="Alice", name_embedding=None),
        ]

        await loader.load_entities(entities)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_entity_with_correct_768_embedding_passes(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """Entities with exactly 768-dim embedding pass validation."""
        embedding_768 = [0.01] * 768
        entities = [
            _make_entity(
                uuid="ent-1",
                canonical_name="ValidEntity",
                entity_type="Person",
                name_embedding=embedding_768,
            ),
        ]

        await loader.load_entities(entities)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["uuid"] == "ent-1"

    @pytest.mark.asyncio
    async def test_entity_validation_logs_warning(
        self, loader, mock_driver: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Skipping entities logs warnings with counts."""
        entities = [
            _make_entity(uuid="ent-1", canonical_name=""),
            _make_entity(
                uuid="ent-2",
                canonical_name="BadDim",
                name_embedding=[0.1] * 256,
            ),
            _make_entity(uuid="ent-3", canonical_name="Good", entity_type="Person"),
        ]

        with caplog.at_level(logging.WARNING, logger="knowledge_base.batch.loader"):
            await loader.load_entities(entities)

        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        # Should have individual skip warnings and a summary
        assert any("data quality" in msg.lower() for msg in warning_messages)

    @pytest.mark.asyncio
    async def test_all_entities_invalid_no_write(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """When all entities are invalid, no Neo4j write occurs."""
        entities = [
            _make_entity(uuid="ent-1", canonical_name=""),
            _make_entity(uuid="ent-2", canonical_name="  "),
        ]

        await loader.load_entities(entities)

        # _execute_batch with empty data skips the write
        mock_driver.execute_query.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Loader relationship validation: load_relationships skips bad relationships
# ---------------------------------------------------------------------------


class TestLoaderRelationshipValidation:
    """Test that load_relationships validates relationships before writing to Neo4j."""

    @pytest.mark.asyncio
    async def test_skips_relationship_with_empty_fact(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """Relationships with empty fact text are skipped."""
        rels = [
            _make_relationship(uuid="rel-bad", fact=""),
            _make_relationship(uuid="rel-good", fact="A valid factual statement."),
        ]

        await loader.load_relationships(rels)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["uuid"] == "rel-good"

    @pytest.mark.asyncio
    async def test_skips_relationship_with_whitespace_only_fact(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """Relationships with whitespace-only fact text are skipped."""
        rels = [
            _make_relationship(uuid="rel-bad", fact="   "),
            _make_relationship(uuid="rel-good", fact="Some fact."),
        ]

        await loader.load_relationships(rels)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["uuid"] == "rel-good"

    @pytest.mark.asyncio
    async def test_skips_relationship_with_wrong_embedding_dim(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """Relationships with fact_embedding dim != 768 are skipped."""
        wrong_dim = [0.5] * 256
        correct_dim = [0.5] * 768

        rels = [
            _make_relationship(
                uuid="rel-bad",
                fact="Bad embedding.",
                fact_embedding=wrong_dim,
            ),
            _make_relationship(
                uuid="rel-good",
                fact="Good embedding.",
                fact_embedding=correct_dim,
            ),
        ]

        await loader.load_relationships(rels)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["uuid"] == "rel-good"

    @pytest.mark.asyncio
    async def test_relationship_without_embedding_passes(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """Relationships with no embedding (None) are valid and pass through."""
        rels = [
            _make_relationship(
                uuid="rel-1",
                fact="A valid fact.",
                fact_embedding=None,
            ),
        ]

        await loader.load_relationships(rels)

        batch_data = mock_driver.execute_query.call_args[1]["params"]["batch"]
        assert len(batch_data) == 1
        assert batch_data[0]["uuid"] == "rel-1"

    @pytest.mark.asyncio
    async def test_relationship_validation_logs_warning(
        self, loader, mock_driver: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Skipping relationships logs warnings with counts."""
        rels = [
            _make_relationship(uuid="rel-1", fact=""),
            _make_relationship(uuid="rel-2", fact="Valid.", fact_embedding=[0.1] * 256),
            _make_relationship(uuid="rel-3", fact="Also valid."),
        ]

        with caplog.at_level(logging.WARNING, logger="knowledge_base.batch.loader"):
            await loader.load_relationships(rels)

        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("data quality" in msg.lower() for msg in warning_messages)

    @pytest.mark.asyncio
    async def test_all_relationships_invalid_no_write(
        self, loader, mock_driver: AsyncMock
    ) -> None:
        """When all relationships are invalid, no Neo4j write occurs."""
        rels = [
            _make_relationship(uuid="rel-1", fact=""),
            _make_relationship(uuid="rel-2", fact="  "),
        ]

        await loader.load_relationships(rels)

        mock_driver.execute_query.assert_not_called()


# ---------------------------------------------------------------------------
# 4. verify_data_quality: returns correct counts and handles errors
# ---------------------------------------------------------------------------


class TestVerifyDataQuality:
    """Test the verify_data_quality function from vector_indices."""

    @pytest.mark.asyncio
    async def test_returns_zero_counts_for_clean_data(
        self, mock_driver: AsyncMock
    ) -> None:
        """All checks return 0 when data is clean."""
        mock_driver.execute_query = AsyncMock(
            return_value=([{"cnt": 0}], None, None)
        )

        result = await verify_data_quality(mock_driver)

        assert result["empty_name_entities"] == 0
        assert result["bad_embedding_entities"] == 0
        assert result["empty_embedding_entities"] == 0

    @pytest.mark.asyncio
    async def test_returns_nonzero_counts_for_bad_data(
        self, mock_driver: AsyncMock
    ) -> None:
        """Counts reflect actual bad records found."""
        # Return different counts for each of the 3 queries
        mock_driver.execute_query = AsyncMock(
            side_effect=[
                ([{"cnt": 5}], None, None),   # empty_name_entities
                ([{"cnt": 12}], None, None),  # bad_embedding_entities
                ([{"cnt": 3}], None, None),   # empty_embedding_entities
            ]
        )

        result = await verify_data_quality(mock_driver)

        assert result["empty_name_entities"] == 5
        assert result["bad_embedding_entities"] == 12
        assert result["empty_embedding_entities"] == 3

    @pytest.mark.asyncio
    async def test_returns_all_three_check_keys(
        self, mock_driver: AsyncMock
    ) -> None:
        """Result dict contains exactly the three expected keys."""
        mock_driver.execute_query = AsyncMock(
            return_value=([{"cnt": 0}], None, None)
        )

        result = await verify_data_quality(mock_driver)

        assert set(result.keys()) == {
            "empty_name_entities",
            "bad_embedding_entities",
            "empty_embedding_entities",
        }

    @pytest.mark.asyncio
    async def test_query_error_returns_negative_one(
        self, mock_driver: AsyncMock
    ) -> None:
        """When a query fails, the check returns -1 instead of crashing."""
        mock_driver.execute_query = AsyncMock(
            side_effect=Exception("Neo4j connection lost")
        )

        result = await verify_data_quality(mock_driver)

        # All three should be -1 since all queries fail
        assert result["empty_name_entities"] == -1
        assert result["bad_embedding_entities"] == -1
        assert result["empty_embedding_entities"] == -1

    @pytest.mark.asyncio
    async def test_partial_query_failure(self, mock_driver: AsyncMock) -> None:
        """When only one query fails, others still return valid counts."""
        mock_driver.execute_query = AsyncMock(
            side_effect=[
                ([{"cnt": 2}], None, None),              # empty_name_entities OK
                Exception("timeout on second query"),     # bad_embedding_entities FAIL
                ([{"cnt": 0}], None, None),              # empty_embedding_entities OK
            ]
        )

        result = await verify_data_quality(mock_driver)

        assert result["empty_name_entities"] == 2
        assert result["bad_embedding_entities"] == -1
        assert result["empty_embedding_entities"] == 0

    @pytest.mark.asyncio
    async def test_empty_records_returns_zero(self, mock_driver: AsyncMock) -> None:
        """When query returns empty records list, count defaults to 0."""
        mock_driver.execute_query = AsyncMock(
            return_value=([], None, None)
        )

        result = await verify_data_quality(mock_driver)

        assert result["empty_name_entities"] == 0
        assert result["bad_embedding_entities"] == 0
        assert result["empty_embedding_entities"] == 0

    @pytest.mark.asyncio
    async def test_nonzero_counts_log_warnings(
        self, mock_driver: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-zero check results produce warning log messages."""
        mock_driver.execute_query = AsyncMock(
            side_effect=[
                ([{"cnt": 7}], None, None),
                ([{"cnt": 0}], None, None),
                ([{"cnt": 0}], None, None),
            ]
        )

        with caplog.at_level(logging.WARNING, logger="knowledge_base.graph.vector_indices"):
            result = await verify_data_quality(mock_driver)

        assert result["empty_name_entities"] == 7
        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "empty_name_entities" in r.message
        ]
        assert len(warning_records) == 1

    @pytest.mark.asyncio
    async def test_error_logs_error_message(
        self, mock_driver: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Query failures produce error log messages."""
        mock_driver.execute_query = AsyncMock(
            side_effect=Exception("connection refused")
        )

        with caplog.at_level(logging.ERROR, logger="knowledge_base.graph.vector_indices"):
            await verify_data_quality(mock_driver)

        error_records = [
            r for r in caplog.records
            if r.levelno >= logging.ERROR and "failed" in r.message.lower()
        ]
        assert len(error_records) >= 1
