"""Tests for HNSW vector index management for Neo4j."""

from unittest.mock import AsyncMock

import pytest

from knowledge_base.graph.vector_indices import (
    EDGE_INDEX_NAME,
    ENTITY_INDEX_NAME,
    VECTOR_INDEX_DIMENSION,
    VECTOR_SIMILARITY_FUNCTION,
    check_vector_indices,
    create_vector_indices,
)


# ---------------------------------------------------------------------------
# create_vector_indices tests
# ---------------------------------------------------------------------------


class TestCreateVectorIndices:
    """Tests for create_vector_indices function."""

    @pytest.mark.asyncio
    async def test_creates_three_indices(self) -> None:
        """create_vector_indices calls execute_query three times (entity + edge + community)."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        await create_vector_indices(mock_driver)

        assert mock_driver.execute_query.call_count == 3

    @pytest.mark.asyncio
    async def test_entity_index_query_structure(self) -> None:
        """Entity index query has correct CREATE VECTOR INDEX syntax."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        await create_vector_indices(mock_driver)

        # First call is entity index
        entity_query = mock_driver.execute_query.call_args_list[0][0][0]
        assert "CREATE VECTOR INDEX" in entity_query
        assert ENTITY_INDEX_NAME in entity_query
        assert "IF NOT EXISTS" in entity_query
        assert "FOR (n:Entity)" in entity_query
        assert "ON (n.name_embedding)" in entity_query

    @pytest.mark.asyncio
    async def test_entity_index_has_correct_dimensions(self) -> None:
        """Entity index specifies 768 dimensions."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        await create_vector_indices(mock_driver)

        entity_query = mock_driver.execute_query.call_args_list[0][0][0]
        assert f"`vector.dimensions`: {VECTOR_INDEX_DIMENSION}" in entity_query
        assert str(768) in entity_query

    @pytest.mark.asyncio
    async def test_entity_index_has_cosine_similarity(self) -> None:
        """Entity index uses cosine similarity function."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        await create_vector_indices(mock_driver)

        entity_query = mock_driver.execute_query.call_args_list[0][0][0]
        assert f"`vector.similarity_function`: '{VECTOR_SIMILARITY_FUNCTION}'" in entity_query
        assert "cosine" in entity_query

    @pytest.mark.asyncio
    async def test_edge_index_query_structure(self) -> None:
        """Edge index query has correct CREATE VECTOR INDEX syntax."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        await create_vector_indices(mock_driver)

        # Second call is edge index
        edge_query = mock_driver.execute_query.call_args_list[1][0][0]
        assert "CREATE VECTOR INDEX" in edge_query
        assert EDGE_INDEX_NAME in edge_query
        assert "IF NOT EXISTS" in edge_query
        assert "FOR ()-[e:RELATES_TO]-()" in edge_query
        assert "ON (e.fact_embedding)" in edge_query

    @pytest.mark.asyncio
    async def test_edge_index_has_correct_dimensions(self) -> None:
        """Edge index specifies 768 dimensions."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        await create_vector_indices(mock_driver)

        edge_query = mock_driver.execute_query.call_args_list[1][0][0]
        assert f"`vector.dimensions`: {VECTOR_INDEX_DIMENSION}" in edge_query
        assert str(768) in edge_query

    @pytest.mark.asyncio
    async def test_edge_index_has_cosine_similarity(self) -> None:
        """Edge index uses cosine similarity function."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        await create_vector_indices(mock_driver)

        edge_query = mock_driver.execute_query.call_args_list[1][0][0]
        assert f"`vector.similarity_function`: '{VECTOR_SIMILARITY_FUNCTION}'" in edge_query
        assert "cosine" in edge_query

    @pytest.mark.asyncio
    async def test_idempotent_with_if_not_exists(self) -> None:
        """Both queries use IF NOT EXISTS for idempotent calls."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        await create_vector_indices(mock_driver)

        entity_query = mock_driver.execute_query.call_args_list[0][0][0]
        edge_query = mock_driver.execute_query.call_args_list[1][0][0]

        assert "IF NOT EXISTS" in entity_query
        assert "IF NOT EXISTS" in edge_query


# ---------------------------------------------------------------------------
# check_vector_indices tests
# ---------------------------------------------------------------------------


class TestCheckVectorIndices:
    """Tests for check_vector_indices function."""

    @pytest.mark.asyncio
    async def test_queries_for_vector_indices(self) -> None:
        """check_vector_indices executes SHOW INDEXES WHERE type = 'VECTOR'."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        await check_vector_indices(mock_driver)

        mock_driver.execute_query.assert_called_once()
        query = mock_driver.execute_query.call_args[0][0]
        assert "SHOW INDEXES" in query
        assert "WHERE type = 'VECTOR'" in query
        assert "RETURN name, state" in query

    @pytest.mark.asyncio
    async def test_returns_index_name_to_state_mapping(self) -> None:
        """Returns dict mapping index name to state."""
        mock_records = [
            {"name": "entity_name_embedding", "state": "ONLINE"},
            {"name": "edge_fact_embedding", "state": "ONLINE"},
        ]
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=(mock_records, None, None))

        result = await check_vector_indices(mock_driver)

        assert result == {
            "entity_name_embedding": "ONLINE",
            "edge_fact_embedding": "ONLINE",
        }

    @pytest.mark.asyncio
    async def test_handles_populating_state(self) -> None:
        """Returns POPULATING state for indices that are building."""
        mock_records = [
            {"name": "entity_name_embedding", "state": "POPULATING"},
        ]
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=(mock_records, None, None))

        result = await check_vector_indices(mock_driver)

        assert result == {"entity_name_embedding": "POPULATING"}

    @pytest.mark.asyncio
    async def test_handles_failed_state(self) -> None:
        """Returns FAILED state for indices that failed to build."""
        mock_records = [
            {"name": "entity_name_embedding", "state": "FAILED"},
        ]
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=(mock_records, None, None))

        result = await check_vector_indices(mock_driver)

        assert result == {"entity_name_embedding": "FAILED"}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_indices(self) -> None:
        """Returns empty dict when no vector indices exist."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        result = await check_vector_indices(mock_driver)

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_mixed_states(self) -> None:
        """Returns correct states when indices have different states."""
        mock_records = [
            {"name": "entity_name_embedding", "state": "ONLINE"},
            {"name": "edge_fact_embedding", "state": "POPULATING"},
            {"name": "other_index", "state": "FAILED"},
        ]
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=(mock_records, None, None))

        result = await check_vector_indices(mock_driver)

        assert result == {
            "entity_name_embedding": "ONLINE",
            "edge_fact_embedding": "POPULATING",
            "other_index": "FAILED",
        }

    @pytest.mark.asyncio
    async def test_only_includes_indices_in_results(self) -> None:
        """Only includes indices that are returned from SHOW INDEXES."""
        mock_records = [
            {"name": "entity_name_embedding", "state": "ONLINE"},
        ]
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=(mock_records, None, None))

        result = await check_vector_indices(mock_driver)

        # edge_fact_embedding not in results
        assert "edge_fact_embedding" not in result
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module constants."""

    def test_vector_dimension_is_768(self) -> None:
        """VECTOR_INDEX_DIMENSION matches Vertex AI text-embedding-005."""
        assert VECTOR_INDEX_DIMENSION == 768

    def test_similarity_function_is_cosine(self) -> None:
        """VECTOR_SIMILARITY_FUNCTION is cosine."""
        assert VECTOR_SIMILARITY_FUNCTION == "cosine"

    def test_entity_index_name(self) -> None:
        """ENTITY_INDEX_NAME is entity_name_embedding."""
        assert ENTITY_INDEX_NAME == "entity_name_embedding"

    def test_edge_index_name(self) -> None:
        """EDGE_INDEX_NAME is edge_fact_embedding."""
        assert EDGE_INDEX_NAME == "edge_fact_embedding"
