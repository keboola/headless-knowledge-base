"""Tests for empty-content search result filtering in GraphitiRetriever.

The search_chunks() method filters out results where
len(sr.content.strip()) < settings.SEARCH_MIN_CONTENT_LENGTH (default 20).
It also always over-fetches 3x from Graphiti to compensate for filtered results.
"""

import logging
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.search.models import SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    chunk_id: str = "c1",
    content: str = "some content",
    score: float = 0.9,
    metadata: dict[str, Any] | None = None,
) -> SearchResult:
    """Create a SearchResult for assertions."""
    return SearchResult(
        chunk_id=chunk_id,
        content=content,
        score=score,
        metadata=metadata or {},
    )


def _make_graphiti_result(
    *,
    name: str = "edge-1",
    fact: str | None = None,
    content: str | None = None,
    source_description: str | None = None,
    score: float = 0.9,
    episodes: list[str] | None = None,
) -> MagicMock:
    """Create a mock Graphiti search result object (edge or entity).

    These are the objects returned by graphiti.search().
    """
    mock = MagicMock()
    mock.name = name
    mock.fact = fact
    mock.content = content
    mock.source_description = source_description
    mock.score = score
    mock.episodes = episodes or [str(uuid.uuid4())]
    mock.uuid = str(uuid.uuid4())
    return mock


def _make_episode_data(
    *,
    name: str = "chunk-1",
    content: str = "A detailed paragraph with enough content to pass the minimum length filter.",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create episode data as returned by _lookup_episodes."""
    return {
        "name": name,
        "content": content,
        "metadata": metadata or {"chunk_id": name},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyContentFiltering:
    """Test that search_chunks filters out results with empty/short content."""

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_empty_content_results_filtered_out(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Results where content is an empty string should be filtered out."""
        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.GRAPH_GROUP_ID = "test"
        mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0
        mock_settings.SEARCH_MIN_CONTENT_LENGTH = 20

        ep_uuid_good = str(uuid.uuid4())
        ep_uuid_empty = str(uuid.uuid4())

        graphiti_results = [
            _make_graphiti_result(name="edge-good", score=0.9, episodes=[ep_uuid_good]),
            _make_graphiti_result(name="edge-empty", score=0.8, episodes=[ep_uuid_empty]),
        ]

        mock_graphiti = AsyncMock()
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        mock_client = MagicMock()
        mock_client.get_client = AsyncMock(return_value=mock_graphiti)
        mock_get_client.return_value = mock_client

        retriever = GraphitiRetriever.__new__(GraphitiRetriever)
        retriever.group_id = "test"
        retriever.client = mock_client
        retriever._graphiti = None

        episode_data = {
            ep_uuid_good: _make_episode_data(
                name="chunk-good",
                content="This is a substantial piece of content that easily passes the filter.",
                metadata={"chunk_id": "chunk-good"},
            ),
            ep_uuid_empty: _make_episode_data(
                name="chunk-empty",
                content="",
                metadata={"chunk_id": "chunk-empty"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data

            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-good"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_whitespace_only_content_filtered(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Results with only whitespace/newlines content should be filtered."""
        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.GRAPH_GROUP_ID = "test"
        mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0
        mock_settings.SEARCH_MIN_CONTENT_LENGTH = 20

        ep_uuid_good = str(uuid.uuid4())
        ep_uuid_ws = str(uuid.uuid4())

        graphiti_results = [
            _make_graphiti_result(name="edge-good", score=0.9, episodes=[ep_uuid_good]),
            _make_graphiti_result(name="edge-ws", score=0.8, episodes=[ep_uuid_ws]),
        ]

        mock_graphiti = AsyncMock()
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        mock_client = MagicMock()
        mock_client.get_client = AsyncMock(return_value=mock_graphiti)
        mock_get_client.return_value = mock_client

        retriever = GraphitiRetriever.__new__(GraphitiRetriever)
        retriever.group_id = "test"
        retriever.client = mock_client
        retriever._graphiti = None

        episode_data = {
            ep_uuid_good: _make_episode_data(
                name="chunk-good",
                content="This is a substantial piece of content that easily passes the filter.",
                metadata={"chunk_id": "chunk-good"},
            ),
            ep_uuid_ws: _make_episode_data(
                name="chunk-ws",
                content="   \n\t  \n   ",
                metadata={"chunk_id": "chunk-ws"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data

            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-good"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_short_edge_fact_filtered(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Results with only a short edge fact (e.g. 'helps_provide', 14 chars < 20) should be filtered."""
        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.GRAPH_GROUP_ID = "test"
        mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0
        mock_settings.SEARCH_MIN_CONTENT_LENGTH = 20

        ep_uuid_good = str(uuid.uuid4())
        # This edge has no episode data -- will fall back to result.content
        ep_uuid_short = str(uuid.uuid4())

        graphiti_results = [
            _make_graphiti_result(name="edge-good", score=0.9, episodes=[ep_uuid_good]),
            _make_graphiti_result(
                name="edge-short",
                score=0.8,
                fact="helps_provide",
                content="helps_provide",  # 14 chars, under the 20-char threshold
                episodes=[ep_uuid_short],
            ),
        ]

        mock_graphiti = AsyncMock()
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        mock_client = MagicMock()
        mock_client.get_client = AsyncMock(return_value=mock_graphiti)
        mock_get_client.return_value = mock_client

        retriever = GraphitiRetriever.__new__(GraphitiRetriever)
        retriever.group_id = "test"
        retriever.client = mock_client
        retriever._graphiti = None

        # Only the good episode has data; the short-fact edge has no episode match
        episode_data = {
            ep_uuid_good: _make_episode_data(
                name="chunk-good",
                content="This is a substantial piece of content that easily passes the filter.",
                metadata={"chunk_id": "chunk-good"},
            ),
            # ep_uuid_short intentionally absent -- no episode data for this edge
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data

            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-good"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_valid_content_passes_through(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Results with 200+ character content should NOT be filtered."""
        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.GRAPH_GROUP_ID = "test"
        mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0
        mock_settings.SEARCH_MIN_CONTENT_LENGTH = 20

        ep_uuid_1 = str(uuid.uuid4())
        ep_uuid_2 = str(uuid.uuid4())

        long_content = (
            "This is a comprehensive piece of documentation that describes the Keboola "
            "platform architecture, including its data pipeline, transformation engine, "
            "and orchestration layer. It provides detailed information about how components "
            "interact with each other."
        )
        assert len(long_content) > 200

        graphiti_results = [
            _make_graphiti_result(name="edge-1", score=0.95, episodes=[ep_uuid_1]),
            _make_graphiti_result(name="edge-2", score=0.85, episodes=[ep_uuid_2]),
        ]

        mock_graphiti = AsyncMock()
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        mock_client = MagicMock()
        mock_client.get_client = AsyncMock(return_value=mock_graphiti)
        mock_get_client.return_value = mock_client

        retriever = GraphitiRetriever.__new__(GraphitiRetriever)
        retriever.group_id = "test"
        retriever.client = mock_client
        retriever._graphiti = None

        episode_data = {
            ep_uuid_1: _make_episode_data(
                name="chunk-1",
                content=long_content,
                metadata={"chunk_id": "chunk-1", "page_title": "Architecture Overview"},
            ),
            ep_uuid_2: _make_episode_data(
                name="chunk-2",
                content="Another valid piece of content with enough characters to pass the filter.",
                metadata={"chunk_id": "chunk-2", "page_title": "Getting Started"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data

            results = await retriever.search_chunks(query="architecture", num_results=10)

        assert len(results) == 2
        assert results[0].chunk_id == "chunk-1"
        assert results[1].chunk_id == "chunk-2"
        assert long_content in results[0].content

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_min_content_length_configurable(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """When SEARCH_MIN_CONTENT_LENGTH=50, a result with 30-char content is filtered."""
        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.GRAPH_GROUP_ID = "test"
        mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0
        mock_settings.SEARCH_MIN_CONTENT_LENGTH = 50  # Higher threshold

        ep_uuid_short = str(uuid.uuid4())
        ep_uuid_long = str(uuid.uuid4())

        short_content = "Thirty chars is not enough."  # 27 chars
        assert len(short_content) < 50
        long_content = "This content is long enough to pass a fifty character minimum threshold for filtering."
        assert len(long_content) >= 50

        graphiti_results = [
            _make_graphiti_result(name="edge-short", score=0.9, episodes=[ep_uuid_short]),
            _make_graphiti_result(name="edge-long", score=0.8, episodes=[ep_uuid_long]),
        ]

        mock_graphiti = AsyncMock()
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        mock_client = MagicMock()
        mock_client.get_client = AsyncMock(return_value=mock_graphiti)
        mock_get_client.return_value = mock_client

        retriever = GraphitiRetriever.__new__(GraphitiRetriever)
        retriever.group_id = "test"
        retriever.client = mock_client
        retriever._graphiti = None

        episode_data = {
            ep_uuid_short: _make_episode_data(
                name="chunk-short",
                content=short_content,
                metadata={"chunk_id": "chunk-short"},
            ),
            ep_uuid_long: _make_episode_data(
                name="chunk-long",
                content=long_content,
                metadata={"chunk_id": "chunk-long"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data

            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-long"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_over_fetch_always_3x(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """graphiti.search() should always be called with num_results * 3."""
        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.GRAPH_GROUP_ID = "test"
        mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0
        mock_settings.SEARCH_MIN_CONTENT_LENGTH = 20

        mock_graphiti = AsyncMock()
        mock_graphiti.search = AsyncMock(return_value=[])

        mock_client = MagicMock()
        mock_client.get_client = AsyncMock(return_value=mock_graphiti)
        mock_get_client.return_value = mock_client

        retriever = GraphitiRetriever.__new__(GraphitiRetriever)
        retriever.group_id = "test"
        retriever.client = mock_client
        retriever._graphiti = None

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {}

            # Request 5 results -- Graphiti should be called with 15 (5 * 3)
            await retriever.search_chunks(query="test", num_results=5)

        mock_graphiti.search.assert_called_once_with(
            query="test",
            num_results=15,  # 5 * 3
            group_ids=["test"],
        )

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_filter_count_logged(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When empty results are filtered, a log message should be emitted with the count."""
        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.GRAPH_GROUP_ID = "test"
        mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0
        mock_settings.SEARCH_MIN_CONTENT_LENGTH = 20

        ep_uuid_good = str(uuid.uuid4())
        ep_uuid_empty_1 = str(uuid.uuid4())
        ep_uuid_empty_2 = str(uuid.uuid4())

        graphiti_results = [
            _make_graphiti_result(name="edge-good", score=0.9, episodes=[ep_uuid_good]),
            _make_graphiti_result(name="edge-empty-1", score=0.8, episodes=[ep_uuid_empty_1]),
            _make_graphiti_result(name="edge-empty-2", score=0.7, episodes=[ep_uuid_empty_2]),
        ]

        mock_graphiti = AsyncMock()
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        mock_client = MagicMock()
        mock_client.get_client = AsyncMock(return_value=mock_graphiti)
        mock_get_client.return_value = mock_client

        retriever = GraphitiRetriever.__new__(GraphitiRetriever)
        retriever.group_id = "test"
        retriever.client = mock_client
        retriever._graphiti = None

        episode_data = {
            ep_uuid_good: _make_episode_data(
                name="chunk-good",
                content="This is a substantial piece of content that easily passes the filter.",
                metadata={"chunk_id": "chunk-good"},
            ),
            ep_uuid_empty_1: _make_episode_data(
                name="chunk-empty-1",
                content="",
                metadata={"chunk_id": "chunk-empty-1"},
            ),
            ep_uuid_empty_2: _make_episode_data(
                name="chunk-empty-2",
                content="   ",
                metadata={"chunk_id": "chunk-empty-2"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data

            with caplog.at_level(logging.INFO, logger="knowledge_base.graph.graphiti_retriever"):
                results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1

        # Verify the filter log message was emitted with correct count
        filter_messages = [
            record.message for record in caplog.records
            if "empty-content" in record.message
        ]
        assert len(filter_messages) == 1
        assert "2/3" in filter_messages[0]  # 2 empty out of 3 total
        assert "min_length=20" in filter_messages[0]
