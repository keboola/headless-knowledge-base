"""Tests for HNSW-backed vector search interface for Neo4j."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from knowledge_base.graph.vector_indices import EDGE_INDEX_NAME, ENTITY_INDEX_NAME
from knowledge_base.graph.vector_search import Neo4jVectorSearchInterface


# ---------------------------------------------------------------------------
# node_similarity_search tests
# ---------------------------------------------------------------------------


class TestNodeSimilaritySearch:
    """Tests for Neo4jVectorSearchInterface.node_similarity_search."""

    @pytest.mark.asyncio
    async def test_generates_hnsw_index_query(self) -> None:
        """Query uses db.index.vector.queryNodes with correct index name."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            limit=10,
        )

        mock_driver.execute_query.assert_called_once()
        query = mock_driver.execute_query.call_args[0][0]

        assert f"CALL db.index.vector.queryNodes('{ENTITY_INDEX_NAME}'" in query
        assert "YIELD node AS n, score" in query

    @pytest.mark.asyncio
    async def test_passes_search_vector_as_parameter(self) -> None:
        """Search vector is passed as a query parameter."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1, 0.2, 0.3]

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            limit=10,
        )

        kwargs = mock_driver.execute_query.call_args[1]
        assert kwargs["search_vector"] == search_vector

    @pytest.mark.asyncio
    async def test_applies_min_score_filter(self) -> None:
        """Query includes WHERE score > $min_score."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            limit=10,
            min_score=0.8,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        assert "WHERE" in query
        assert "score > $min_score" in query
        assert kwargs["min_score"] == 0.8

    @pytest.mark.asyncio
    async def test_applies_limit(self) -> None:
        """Query includes LIMIT $limit."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            limit=25,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        assert "LIMIT $limit" in query
        assert kwargs["limit"] == 25

    @pytest.mark.asyncio
    async def test_orders_by_score_desc(self) -> None:
        """Query orders results by score descending."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        assert "ORDER BY score DESC" in query

    @pytest.mark.asyncio
    async def test_fetch_limit_without_group_ids(self) -> None:
        """When group_ids is None, fetch_limit equals limit (no over-fetching)."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            group_ids=None,
            limit=10,
        )

        kwargs = mock_driver.execute_query.call_args[1]
        assert kwargs["fetch_limit"] == 10

    @pytest.mark.asyncio
    async def test_fetch_limit_with_group_ids(self) -> None:
        """When group_ids is set, fetch_limit is limit * 3 (over-fetch for filtering)."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            group_ids=["default", "team-1"],
            limit=10,
        )

        kwargs = mock_driver.execute_query.call_args[1]
        assert kwargs["fetch_limit"] == 30  # 10 * 3

    @pytest.mark.asyncio
    async def test_applies_group_id_filter(self) -> None:
        """When group_ids is set, query includes n.group_id IN $group_ids."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            group_ids=["default", "team-1"],
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        assert "n.group_id IN $group_ids" in query
        assert kwargs["group_ids"] == ["default", "team-1"]

    @pytest.mark.asyncio
    async def test_no_group_id_filter_when_none(self) -> None:
        """When group_ids is None, no group_id filter in query."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            group_ids=None,
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        assert "n.group_id IN $group_ids" not in query
        assert "group_ids" not in kwargs

    @pytest.mark.asyncio
    async def test_uses_read_routing(self) -> None:
        """Query uses read routing (routing_='r')."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            limit=10,
        )

        kwargs = mock_driver.execute_query.call_args[1]
        assert kwargs["routing_"] == "r"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.vector_search.get_entity_node_from_record")
    async def test_returns_entity_nodes(self, mock_get_node: AsyncMock) -> None:
        """Returns list of EntityNode objects from records."""
        # Mock record data
        mock_records = [
            {
                "uuid": "u1",
                "name": "Entity A",
                "group_id": "default",
                "created_at": datetime(2025, 1, 1),
                "summary": "Test entity A",
                "labels": ["Entity"],
                "attributes": {},
            },
            {
                "uuid": "u2",
                "name": "Entity B",
                "group_id": "default",
                "created_at": datetime(2025, 1, 2),
                "summary": "Test entity B",
                "labels": ["Entity"],
                "attributes": {},
            },
        ]

        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=(mock_records, None, None))

        # Mock node objects
        from graphiti_core.nodes import EntityNode

        mock_nodes = [
            EntityNode(
                uuid="u1",
                name="Entity A",
                group_id="default",
                created_at=datetime(2025, 1, 1),
                summary="Test entity A",
                labels=["Entity"],
                attributes={},
            ),
            EntityNode(
                uuid="u2",
                name="Entity B",
                group_id="default",
                created_at=datetime(2025, 1, 2),
                summary="Test entity B",
                labels=["Entity"],
                attributes={},
            ),
        ]
        mock_get_node.side_effect = mock_nodes

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        result = await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            limit=10,
        )

        assert len(result) == 2
        assert all(isinstance(node, EntityNode) for node in result)
        assert result[0].uuid == "u1"
        assert result[1].uuid == "u2"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_results(self) -> None:
        """Returns empty list when no nodes match."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        result = await interface.node_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            search_filter=None,
            limit=10,
        )

        assert result == []


# ---------------------------------------------------------------------------
# edge_similarity_search tests
# ---------------------------------------------------------------------------


class TestEdgeSimilaritySearch:
    """Tests for Neo4jVectorSearchInterface.edge_similarity_search."""

    @pytest.mark.asyncio
    async def test_generates_hnsw_index_query(self) -> None:
        """Query uses db.index.vector.queryRelationships with correct index name."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            limit=10,
        )

        mock_driver.execute_query.assert_called_once()
        query = mock_driver.execute_query.call_args[0][0]

        assert f"CALL db.index.vector.queryRelationships('{EDGE_INDEX_NAME}'" in query
        assert "YIELD relationship AS e, score" in query

    @pytest.mark.asyncio
    async def test_matches_edge_endpoints(self) -> None:
        """Query includes MATCH (n:Entity)-[e]->(m:Entity) to get endpoints."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        assert "MATCH (n:Entity)-[e]->(m:Entity)" in query

    @pytest.mark.asyncio
    async def test_applies_min_score_filter(self) -> None:
        """Query includes WHERE score > $min_score."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            limit=10,
            min_score=0.75,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        assert "WHERE" in query
        assert "score > $min_score" in query
        assert kwargs["min_score"] == 0.75

    @pytest.mark.asyncio
    async def test_includes_score_in_return(self) -> None:
        """Query includes score in RETURN for ORDER BY compatibility."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        assert "score" in query
        assert "RETURN" in query

    @pytest.mark.asyncio
    async def test_orders_by_score_desc(self) -> None:
        """Query orders results by score descending."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        assert "ORDER BY score DESC" in query

    @pytest.mark.asyncio
    async def test_fetch_limit_without_filters(self) -> None:
        """When no filters, fetch_limit equals limit (no over-fetching)."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            group_ids=None,
            limit=10,
        )

        kwargs = mock_driver.execute_query.call_args[1]
        assert kwargs["fetch_limit"] == 10

    @pytest.mark.asyncio
    async def test_fetch_limit_with_group_ids(self) -> None:
        """When group_ids is set, fetch_limit is limit * 3."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            group_ids=["default"],
            limit=10,
        )

        kwargs = mock_driver.execute_query.call_args[1]
        assert kwargs["fetch_limit"] == 30  # 10 * 3

    @pytest.mark.asyncio
    async def test_fetch_limit_with_source_uuid(self) -> None:
        """When source_node_uuid is set, fetch_limit is limit * 3."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid="u1",
            target_node_uuid=None,
            search_filter=None,
            group_ids=None,
            limit=10,
        )

        kwargs = mock_driver.execute_query.call_args[1]
        assert kwargs["fetch_limit"] == 30  # 10 * 3

    @pytest.mark.asyncio
    async def test_fetch_limit_with_target_uuid(self) -> None:
        """When target_node_uuid is set, fetch_limit is limit * 3."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid="u2",
            search_filter=None,
            group_ids=None,
            limit=10,
        )

        kwargs = mock_driver.execute_query.call_args[1]
        assert kwargs["fetch_limit"] == 30  # 10 * 3

    @pytest.mark.asyncio
    async def test_applies_group_id_filter(self) -> None:
        """When group_ids is set, query includes e.group_id IN $group_ids."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            group_ids=["default", "team-1"],
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        assert "e.group_id IN $group_ids" in query
        assert kwargs["group_ids"] == ["default", "team-1"]

    @pytest.mark.asyncio
    async def test_applies_source_node_uuid_filter(self) -> None:
        """When source_node_uuid is set, query includes n.uuid = $source_uuid."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid="source-123",
            target_node_uuid=None,
            search_filter=None,
            group_ids=None,
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        assert "n.uuid = $source_uuid" in query
        assert kwargs["source_uuid"] == "source-123"

    @pytest.mark.asyncio
    async def test_applies_target_node_uuid_filter(self) -> None:
        """When target_node_uuid is set, query includes m.uuid = $target_uuid."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid="target-456",
            search_filter=None,
            group_ids=None,
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        assert "m.uuid = $target_uuid" in query
        assert kwargs["target_uuid"] == "target-456"

    @pytest.mark.asyncio
    async def test_applies_multiple_filters(self) -> None:
        """When multiple filters are set, all are included in WHERE clause."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid="source-123",
            target_node_uuid="target-456",
            search_filter=None,
            group_ids=["default"],
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        # All filters should be in WHERE clause
        assert "score > $min_score" in query
        assert "e.group_id IN $group_ids" in query
        assert "n.uuid = $source_uuid" in query
        assert "m.uuid = $target_uuid" in query

        # All params should be present
        assert kwargs["group_ids"] == ["default"]
        assert kwargs["source_uuid"] == "source-123"
        assert kwargs["target_uuid"] == "target-456"

    @pytest.mark.asyncio
    async def test_no_filters_when_none(self) -> None:
        """When no filters are set, only min_score filter is applied."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            group_ids=None,
            limit=10,
        )

        query = mock_driver.execute_query.call_args[0][0]
        kwargs = mock_driver.execute_query.call_args[1]

        # Only min_score filter
        assert "score > $min_score" in query
        assert "e.group_id IN $group_ids" not in query
        assert "n.uuid = $source_uuid" not in query
        assert "m.uuid = $target_uuid" not in query

        # No filter params
        assert "group_ids" not in kwargs
        assert "source_uuid" not in kwargs
        assert "target_uuid" not in kwargs

    @pytest.mark.asyncio
    async def test_uses_read_routing(self) -> None:
        """Query uses read routing (routing_='r')."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            limit=10,
        )

        kwargs = mock_driver.execute_query.call_args[1]
        assert kwargs["routing_"] == "r"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.vector_search.get_entity_edge_from_record")
    async def test_returns_entity_edges(self, mock_get_edge: AsyncMock) -> None:
        """Returns list of EntityEdge objects from records."""
        # Mock record data
        mock_records = [
            {
                "uuid": "e1",
                "source_node_uuid": "u1",
                "target_node_uuid": "u2",
                "group_id": "default",
                "created_at": datetime(2025, 1, 1),
                "name": "relates_to",
                "fact": "A relates to B",
                "episodes": ["ep1"],
                "expired_at": None,
                "valid_at": datetime(2025, 1, 1),
                "invalid_at": None,
                "attributes": {},
            },
            {
                "uuid": "e2",
                "source_node_uuid": "u2",
                "target_node_uuid": "u3",
                "group_id": "default",
                "created_at": datetime(2025, 1, 2),
                "name": "connects_to",
                "fact": "B connects to C",
                "episodes": ["ep2"],
                "expired_at": None,
                "valid_at": datetime(2025, 1, 2),
                "invalid_at": None,
                "attributes": {},
            },
        ]

        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=(mock_records, None, None))

        # Mock edge objects
        from graphiti_core.edges import EntityEdge

        mock_edges = [
            EntityEdge(
                uuid="e1",
                source_node_uuid="u1",
                target_node_uuid="u2",
                group_id="default",
                created_at=datetime(2025, 1, 1),
                name="relates_to",
                fact="A relates to B",
                episodes=["ep1"],
                expired_at=None,
                valid_at=datetime(2025, 1, 1),
                invalid_at=None,
                attributes={},
            ),
            EntityEdge(
                uuid="e2",
                source_node_uuid="u2",
                target_node_uuid="u3",
                group_id="default",
                created_at=datetime(2025, 1, 2),
                name="connects_to",
                fact="B connects to C",
                episodes=["ep2"],
                expired_at=None,
                valid_at=datetime(2025, 1, 2),
                invalid_at=None,
                attributes={},
            ),
        ]
        mock_get_edge.side_effect = mock_edges

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        result = await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            limit=10,
        )

        assert len(result) == 2
        assert all(isinstance(edge, EntityEdge) for edge in result)
        assert result[0].uuid == "e1"
        assert result[1].uuid == "e2"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_results(self) -> None:
        """Returns empty list when no edges match."""
        mock_driver = AsyncMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        interface = Neo4jVectorSearchInterface()
        search_vector = [0.1] * 768

        result = await interface.edge_similarity_search(
            driver=mock_driver,
            search_vector=search_vector,
            source_node_uuid=None,
            target_node_uuid=None,
            search_filter=None,
            limit=10,
        )

        assert result == []


# ---------------------------------------------------------------------------
# SearchInterface inheritance tests
# ---------------------------------------------------------------------------


class TestSearchInterfaceInheritance:
    """Tests for SearchInterface inheritance and interface compliance."""

    def test_inherits_from_search_interface(self) -> None:
        """Neo4jVectorSearchInterface inherits from SearchInterface."""
        from graphiti_core.driver.search_interface.search_interface import SearchInterface

        interface = Neo4jVectorSearchInterface()
        assert isinstance(interface, SearchInterface)

    def test_implements_node_similarity_search(self) -> None:
        """Implements node_similarity_search method."""
        interface = Neo4jVectorSearchInterface()
        assert hasattr(interface, "node_similarity_search")
        assert callable(interface.node_similarity_search)

    def test_implements_edge_similarity_search(self) -> None:
        """Implements edge_similarity_search method."""
        interface = Neo4jVectorSearchInterface()
        assert hasattr(interface, "edge_similarity_search")
        assert callable(interface.edge_similarity_search)

    def test_implements_fulltext_passthrough_methods(self) -> None:
        """Implements all fulltext passthrough methods."""
        interface = Neo4jVectorSearchInterface()
        assert callable(interface.edge_fulltext_search)
        assert callable(interface.node_fulltext_search)
        assert callable(interface.episode_fulltext_search)
        assert callable(interface.community_fulltext_search)
        assert callable(interface.community_similarity_search)


# ---------------------------------------------------------------------------
# Passthrough delegation tests
# ---------------------------------------------------------------------------


class TestPassthroughDelegation:
    """Tests that fulltext/community methods delegate to Graphiti defaults."""

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.vector_search.search_utils")
    async def test_edge_fulltext_delegates_to_default(self, mock_search_utils: AsyncMock) -> None:
        """edge_fulltext_search delegates to search_utils.edge_fulltext_search."""
        mock_search_utils.edge_fulltext_search = AsyncMock(return_value=[])

        mock_driver = AsyncMock()
        mock_driver.search_interface = None  # Will be set by interface

        interface = Neo4jVectorSearchInterface()
        mock_driver.search_interface = interface

        await interface.edge_fulltext_search(
            driver=mock_driver, query="test", search_filter=None, group_ids=["default"], limit=10
        )

        mock_search_utils.edge_fulltext_search.assert_called_once_with(
            mock_driver, "test", None, ["default"], 10
        )

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.vector_search.search_utils")
    async def test_node_fulltext_delegates_to_default(self, mock_search_utils: AsyncMock) -> None:
        """node_fulltext_search delegates to search_utils.node_fulltext_search."""
        mock_search_utils.node_fulltext_search = AsyncMock(return_value=[])

        mock_driver = AsyncMock()
        interface = Neo4jVectorSearchInterface()
        mock_driver.search_interface = interface

        await interface.node_fulltext_search(
            driver=mock_driver, query="test", search_filter=None, group_ids=None, limit=5
        )

        mock_search_utils.node_fulltext_search.assert_called_once_with(
            mock_driver, "test", None, None, 5
        )

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.vector_search.search_utils")
    async def test_episode_fulltext_delegates_to_default(self, mock_search_utils: AsyncMock) -> None:
        """episode_fulltext_search delegates to search_utils.episode_fulltext_search."""
        mock_search_utils.episode_fulltext_search = AsyncMock(return_value=[])

        mock_driver = AsyncMock()
        interface = Neo4jVectorSearchInterface()
        mock_driver.search_interface = interface

        await interface.episode_fulltext_search(
            driver=mock_driver, query="test", search_filter=None, group_ids=["g1"], limit=20
        )

        mock_search_utils.episode_fulltext_search.assert_called_once_with(
            mock_driver, "test", None, ["g1"], 20
        )

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.vector_search.search_utils")
    async def test_passthrough_temporarily_removes_interface(self, mock_search_utils: AsyncMock) -> None:
        """Passthrough methods remove search_interface during delegation to avoid recursion."""
        interface_during_call = None

        async def capture_interface(driver, *args, **kwargs):
            nonlocal interface_during_call
            interface_during_call = driver.search_interface
            return []

        mock_search_utils.edge_fulltext_search = capture_interface

        mock_driver = AsyncMock()
        interface = Neo4jVectorSearchInterface()
        mock_driver.search_interface = interface

        await interface.edge_fulltext_search(
            driver=mock_driver, query="test", search_filter=None
        )

        # During the call, search_interface should have been None
        assert interface_during_call is None
        # After the call, it should be restored
        assert mock_driver.search_interface is interface
