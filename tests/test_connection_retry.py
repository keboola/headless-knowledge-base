"""Tests for Neo4j stale connection retry logic.

Tests the _is_connection_error() helper and retry-with-reset behavior
in GraphitiRetriever.search_chunks() and _lookup_episodes().
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from knowledge_base.graph.graphiti_retriever import (
    _is_connection_error,
    GraphitiRetriever,
    SearchResult,
)


class TestIsConnectionError:
    """Tests for the _is_connection_error() helper."""

    def test_runtime_error_tcp_transport(self):
        """RuntimeError with TCPTransport is a connection error."""
        exc = RuntimeError("unable to perform operation on <TCPTransport closed=True>")
        assert _is_connection_error(exc) is True

    def test_runtime_error_other(self):
        """RuntimeError without TCPTransport is NOT a connection error."""
        exc = RuntimeError("some other runtime error")
        assert _is_connection_error(exc) is False

    def test_os_error(self):
        """OSError (broken pipe, connection reset) is a connection error."""
        exc = OSError("Connection reset by peer")
        assert _is_connection_error(exc) is True

    def test_connection_refused(self):
        """ConnectionRefusedError (subclass of OSError) is a connection error."""
        exc = ConnectionRefusedError("Connection refused")
        assert _is_connection_error(exc) is True

    def test_service_unavailable(self):
        """neo4j.exceptions.ServiceUnavailable is a connection error."""
        try:
            from neo4j.exceptions import ServiceUnavailable
            exc = ServiceUnavailable("Server unavailable")
            assert _is_connection_error(exc) is True
        except ImportError:
            pytest.skip("neo4j package not installed")

    def test_session_expired(self):
        """neo4j.exceptions.SessionExpired is a connection error."""
        try:
            from neo4j.exceptions import SessionExpired
            exc = SessionExpired("Session expired")
            assert _is_connection_error(exc) is True
        except ImportError:
            pytest.skip("neo4j package not installed")

    def test_value_error_not_connection(self):
        """ValueError is NOT a connection error."""
        exc = ValueError("invalid value")
        assert _is_connection_error(exc) is False

    def test_key_error_not_connection(self):
        """KeyError is NOT a connection error."""
        exc = KeyError("missing key")
        assert _is_connection_error(exc) is False

    def test_generic_exception_not_connection(self):
        """Generic Exception is NOT a connection error."""
        exc = Exception("something went wrong")
        assert _is_connection_error(exc) is False


class TestSearchChunksRetry:
    """Tests for retry behavior in GraphitiRetriever.search_chunks()."""

    @pytest.fixture
    def retriever(self):
        """Create a GraphitiRetriever with mocked client."""
        with patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client") as mock_get:
            mock_client = MagicMock()
            mock_client.get_client = AsyncMock()
            mock_client.reset_and_reconnect = AsyncMock()
            mock_get.return_value = mock_client
            retriever = GraphitiRetriever()
            yield retriever

    @pytest.mark.asyncio
    async def test_retries_on_tcp_transport_error(self, retriever):
        """search_chunks retries once on TCPTransport RuntimeError."""
        mock_graphiti = AsyncMock()
        # First call raises connection error, second succeeds
        mock_result = MagicMock()
        mock_result.episodes = []
        mock_result.score = 0.9
        mock_result.content = "test content"
        mock_result.name = "test"
        mock_result.source_description = None
        mock_result.fact = None

        mock_graphiti.search = AsyncMock(
            side_effect=[
                RuntimeError("unable to perform operation on <TCPTransport closed=True>"),
                [mock_result],
            ]
        )
        retriever._graphiti = mock_graphiti

        with patch.object(retriever, "_get_graphiti", new_callable=AsyncMock, return_value=mock_graphiti):
            # Make _get_graphiti return the mock on retry too
            retriever._get_graphiti = AsyncMock(return_value=mock_graphiti)
            results = await retriever.search_chunks("test query")

        assert len(results) == 1
        assert retriever.client.reset_and_reconnect.call_count == 1
        assert mock_graphiti.search.call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_regular_error(self, retriever):
        """search_chunks does NOT retry on non-connection errors."""
        mock_graphiti = AsyncMock()
        mock_graphiti.search = AsyncMock(side_effect=ValueError("bad query"))
        retriever._graphiti = mock_graphiti
        retriever._get_graphiti = AsyncMock(return_value=mock_graphiti)

        results = await retriever.search_chunks("test query")

        assert results == []
        assert retriever.client.reset_and_reconnect.call_count == 0
        assert mock_graphiti.search.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_empty_after_exhausted_retries(self, retriever):
        """search_chunks returns empty list when all retries fail."""
        mock_graphiti = AsyncMock()
        mock_graphiti.search = AsyncMock(
            side_effect=RuntimeError("unable to perform operation on <TCPTransport closed=True>")
        )
        retriever._graphiti = mock_graphiti
        retriever._get_graphiti = AsyncMock(return_value=mock_graphiti)

        results = await retriever.search_chunks("test query")

        assert results == []
        assert retriever.client.reset_and_reconnect.call_count == 1
        # 2 attempts: initial + 1 retry
        assert mock_graphiti.search.call_count == 2

    @pytest.mark.asyncio
    async def test_succeeds_without_retry(self, retriever):
        """search_chunks succeeds on first attempt without retry."""
        mock_graphiti = AsyncMock()
        mock_result = MagicMock()
        mock_result.episodes = []
        mock_result.score = 0.9
        mock_result.content = "test content"
        mock_result.name = "test"
        mock_result.source_description = None
        mock_result.fact = None

        mock_graphiti.search = AsyncMock(return_value=[mock_result])
        retriever._graphiti = mock_graphiti
        retriever._get_graphiti = AsyncMock(return_value=mock_graphiti)

        results = await retriever.search_chunks("test query")

        assert len(results) == 1
        assert retriever.client.reset_and_reconnect.call_count == 0
        assert mock_graphiti.search.call_count == 1


class TestLookupEpisodesRetry:
    """Tests for retry behavior in GraphitiRetriever._lookup_episodes()."""

    @pytest.fixture
    def retriever(self):
        """Create a GraphitiRetriever with mocked client."""
        with patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client") as mock_get:
            mock_client = MagicMock()
            mock_client.get_client = AsyncMock()
            mock_client.reset_and_reconnect = AsyncMock()
            mock_get.return_value = mock_client
            retriever = GraphitiRetriever()
            yield retriever

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self, retriever):
        """_lookup_episodes retries on connection error."""
        mock_driver = MagicMock()
        mock_record = {"uuid": "abc-123", "name": "test", "content": "hello", "source_desc": None}
        mock_driver.execute_query = AsyncMock(
            side_effect=[
                RuntimeError("unable to perform operation on <TCPTransport closed=True>"),
                ([mock_record], None, None),
            ]
        )

        mock_graphiti = MagicMock()
        mock_graphiti.driver = mock_driver
        retriever._graphiti = mock_graphiti
        retriever._get_graphiti = AsyncMock(return_value=mock_graphiti)

        result = await retriever._lookup_episodes(["abc-123"])

        assert "abc-123" in result
        assert retriever.client.reset_and_reconnect.call_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_regular_error(self, retriever):
        """_lookup_episodes does NOT retry on non-connection errors."""
        mock_driver = MagicMock()
        mock_driver.execute_query = AsyncMock(side_effect=ValueError("bad query"))

        mock_graphiti = MagicMock()
        mock_graphiti.driver = mock_driver
        retriever._graphiti = mock_graphiti
        retriever._get_graphiti = AsyncMock(return_value=mock_graphiti)

        result = await retriever._lookup_episodes(["abc-123"])

        assert result == {}
        assert retriever.client.reset_and_reconnect.call_count == 0

    @pytest.mark.asyncio
    async def test_empty_uuids_returns_empty(self, retriever):
        """_lookup_episodes returns empty for empty UUID list."""
        result = await retriever._lookup_episodes([])
        assert result == {}
