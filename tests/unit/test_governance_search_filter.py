"""Tests for governance-aware search filtering in GraphitiRetriever.

When GOVERNANCE_ENABLED=True, search_chunks() filters out episodes whose
metadata governance_status is not 'approved'. Episodes without the field
default to 'approved' for backward compatibility with existing 196K+ episodes.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graphiti_result(
    *,
    name: str = "edge-1",
    fact: str | None = None,
    content: str | None = None,
    source_description: str | None = None,
    score: float = 0.9,
    episodes: list[str] | None = None,
) -> MagicMock:
    """Create a mock Graphiti search result object (edge or entity)."""
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


def _setup_retriever(mock_settings: MagicMock, mock_get_client: MagicMock, *, governance_enabled: bool = True) -> Any:
    """Create a GraphitiRetriever with mocked dependencies."""
    from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

    mock_settings.GRAPH_ENABLE_GRAPHITI = True
    mock_settings.GRAPH_GROUP_ID = "test"
    mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0
    mock_settings.SEARCH_MIN_CONTENT_LENGTH = 20
    mock_settings.GOVERNANCE_ENABLED = governance_enabled

    mock_graphiti = AsyncMock()
    mock_client = MagicMock()
    mock_client.get_client = AsyncMock(return_value=mock_graphiti)
    mock_get_client.return_value = mock_client

    retriever = GraphitiRetriever.__new__(GraphitiRetriever)
    retriever.group_id = "test"
    retriever.client = mock_client
    retriever._graphiti = None

    return retriever, mock_graphiti


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGovernanceSearchFilter:
    """Test governance-aware filtering in search_chunks()."""

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_approved_episodes_included(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Episodes with governance_status='approved' are included in results."""
        retriever, mock_graphiti = _setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True
        )

        ep_uuid = str(uuid.uuid4())
        graphiti_results = [
            _make_graphiti_result(name="edge-approved", score=0.9, episodes=[ep_uuid]),
        ]
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        episode_data = {
            ep_uuid: _make_episode_data(
                name="chunk-approved",
                content="This content is approved and should appear in results.",
                metadata={"chunk_id": "chunk-approved", "governance_status": "approved"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data
            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-approved"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_pending_episodes_excluded_when_enabled(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Episodes with governance_status='pending' are filtered out when GOVERNANCE_ENABLED=True."""
        retriever, mock_graphiti = _setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True
        )

        ep_uuid_approved = str(uuid.uuid4())
        ep_uuid_pending = str(uuid.uuid4())

        graphiti_results = [
            _make_graphiti_result(name="edge-approved", score=0.9, episodes=[ep_uuid_approved]),
            _make_graphiti_result(name="edge-pending", score=0.8, episodes=[ep_uuid_pending]),
        ]
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        episode_data = {
            ep_uuid_approved: _make_episode_data(
                name="chunk-approved",
                content="This content is approved and should appear in results.",
                metadata={"chunk_id": "chunk-approved", "governance_status": "approved"},
            ),
            ep_uuid_pending: _make_episode_data(
                name="chunk-pending",
                content="This content is pending review and should NOT appear.",
                metadata={"chunk_id": "chunk-pending", "governance_status": "pending"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data
            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-approved"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_missing_governance_status_defaults_approved(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Episodes without governance_status field are treated as approved (backward compat)."""
        retriever, mock_graphiti = _setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True
        )

        ep_uuid = str(uuid.uuid4())
        graphiti_results = [
            _make_graphiti_result(name="edge-legacy", score=0.9, episodes=[ep_uuid]),
        ]
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        # No governance_status in metadata -- should default to 'approved'
        episode_data = {
            ep_uuid: _make_episode_data(
                name="chunk-legacy",
                content="This is legacy content without governance metadata present.",
                metadata={"chunk_id": "chunk-legacy", "page_title": "Old Page"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data
            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-legacy"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_filter_disabled_when_governance_off(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Pending episodes NOT filtered when GOVERNANCE_ENABLED=False."""
        retriever, mock_graphiti = _setup_retriever(
            mock_settings, mock_get_client, governance_enabled=False
        )

        ep_uuid_approved = str(uuid.uuid4())
        ep_uuid_pending = str(uuid.uuid4())

        graphiti_results = [
            _make_graphiti_result(name="edge-approved", score=0.9, episodes=[ep_uuid_approved]),
            _make_graphiti_result(name="edge-pending", score=0.8, episodes=[ep_uuid_pending]),
        ]
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        episode_data = {
            ep_uuid_approved: _make_episode_data(
                name="chunk-approved",
                content="Approved content that should appear in search results.",
                metadata={"chunk_id": "chunk-approved", "governance_status": "approved"},
            ),
            ep_uuid_pending: _make_episode_data(
                name="chunk-pending",
                content="Pending content that should ALSO appear when governance is off.",
                metadata={"chunk_id": "chunk-pending", "governance_status": "pending"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data
            results = await retriever.search_chunks(query="test query", num_results=10)

        # Both should be included when governance is off
        assert len(results) == 2
        chunk_ids = {r.chunk_id for r in results}
        assert "chunk-approved" in chunk_ids
        assert "chunk-pending" in chunk_ids

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_rejected_episodes_excluded(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Episodes with governance_status='rejected' are excluded when governance is enabled."""
        retriever, mock_graphiti = _setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True
        )

        ep_uuid_good = str(uuid.uuid4())
        ep_uuid_rejected = str(uuid.uuid4())

        graphiti_results = [
            _make_graphiti_result(name="edge-good", score=0.9, episodes=[ep_uuid_good]),
            _make_graphiti_result(name="edge-rejected", score=0.8, episodes=[ep_uuid_rejected]),
        ]
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        episode_data = {
            ep_uuid_good: _make_episode_data(
                name="chunk-good",
                content="This content is approved and should appear in results.",
                metadata={"chunk_id": "chunk-good", "governance_status": "approved"},
            ),
            ep_uuid_rejected: _make_episode_data(
                name="chunk-rejected",
                content="This content was rejected and should NOT appear in results.",
                metadata={"chunk_id": "chunk-rejected", "governance_status": "rejected"},
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
    async def test_reverted_episodes_excluded(
        self,
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
    ) -> None:
        """Episodes with governance_status='reverted' are excluded when governance is enabled."""
        retriever, mock_graphiti = _setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True
        )

        ep_uuid_good = str(uuid.uuid4())
        ep_uuid_reverted = str(uuid.uuid4())

        graphiti_results = [
            _make_graphiti_result(name="edge-good", score=0.9, episodes=[ep_uuid_good]),
            _make_graphiti_result(name="edge-reverted", score=0.8, episodes=[ep_uuid_reverted]),
        ]
        mock_graphiti.search = AsyncMock(return_value=graphiti_results)

        episode_data = {
            ep_uuid_good: _make_episode_data(
                name="chunk-good",
                content="This content is approved and should appear in results.",
                metadata={"chunk_id": "chunk-good", "governance_status": "approved"},
            ),
            ep_uuid_reverted: _make_episode_data(
                name="chunk-reverted",
                content="This content was reverted and should NOT appear in results.",
                metadata={"chunk_id": "chunk-reverted", "governance_status": "reverted"},
            ),
        }

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = episode_data
            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-good"