"""Tests for community search functionality."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from knowledge_base.graph.graphiti_retriever import GraphitiRetriever


class TestCommunitySearch:
    """Tests for search_communities method."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_disabled(self):
        """When COMMUNITY_DETECTION_ENABLED=False, returns empty."""
        with patch("knowledge_base.graph.graphiti_retriever.settings") as mock_settings:
            mock_settings.GRAPH_ENABLE_GRAPHITI = True
            mock_settings.COMMUNITY_DETECTION_ENABLED = False
            mock_settings.GRAPH_GROUP_ID = "default"
            mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0

            retriever = GraphitiRetriever.__new__(GraphitiRetriever)
            retriever.group_id = "default"
            retriever.client = MagicMock()
            retriever._graphiti = None

            results = await retriever.search_communities("test query")
            assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_graphiti_disabled(self):
        """When Graphiti is disabled, returns empty."""
        with patch("knowledge_base.graph.graphiti_retriever.settings") as mock_settings:
            mock_settings.GRAPH_ENABLE_GRAPHITI = False
            mock_settings.COMMUNITY_DETECTION_ENABLED = True
            mock_settings.GRAPH_GROUP_ID = "default"

            retriever = GraphitiRetriever.__new__(GraphitiRetriever)
            retriever.group_id = "default"
            retriever.client = MagicMock()
            retriever._graphiti = None

            results = await retriever.search_communities("test query")
            assert results == []
