"""Tests for search scoring using Graphiti search_() with RRF reranker scores.

Verifies that search_chunks() propagates real RRF scores from search_()
instead of falling back to a constant 1.0 for all results.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.graph.graphiti_retriever import GraphitiRetriever, SearchResult


def _make_episode_metadata(chunk_id: str, page_title: str = "Test Page") -> str:
    """Build a JSON source_description for an episode."""
    return json.dumps({
        "chunk_id": chunk_id,
        "page_title": page_title,
        "space_key": "ENG",
        "url": f"https://wiki.example.com/{chunk_id}",
    })


def _make_edge(uuid: str, fact: str, episode_uuids: list[str]) -> MagicMock:
    """Create a mock EntityEdge."""
    edge = MagicMock()
    edge.uuid = uuid
    edge.name = f"edge-{uuid}"
    edge.fact = fact
    edge.episodes = episode_uuids
    edge.source_description = None
    edge.content = ""
    return edge


def _make_episode(uuid: str, chunk_id: str, content: str) -> MagicMock:
    """Create a mock EpisodicNode."""
    ep = MagicMock()
    ep.uuid = uuid
    ep.name = chunk_id
    ep.content = content
    ep.source_description = _make_episode_metadata(chunk_id)
    ep.created_at = datetime.now(timezone.utc)
    return ep


def _make_search_results(
    edges: list | None = None,
    edge_scores: list[float] | None = None,
    episodes: list | None = None,
    episode_scores: list[float] | None = None,
) -> MagicMock:
    """Create a mock SearchResults object."""
    sr = MagicMock()
    sr.edges = edges or []
    sr.edge_reranker_scores = edge_scores or []
    sr.episodes = episodes or []
    sr.episode_reranker_scores = episode_scores or []
    sr.nodes = []
    sr.node_reranker_scores = []
    sr.communities = []
    sr.community_reranker_scores = []
    return sr


@pytest.fixture
def retriever():
    """Create a GraphitiRetriever with mocked client."""
    with patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client") as mock_client:
        mock_client.return_value = MagicMock()
        r = GraphitiRetriever(group_id="test")
        yield r


@pytest.mark.asyncio
async def test_search_chunks_uses_rrf_scores(retriever):
    """search_chunks() should return results with varying RRF scores, not constant 1.0."""
    ep1 = _make_episode("ep-1", "chunk-001", "Content about data pipelines and ETL processes.")
    ep2 = _make_episode("ep-2", "chunk-002", "Content about Snowflake warehousing.")
    ep3 = _make_episode("ep-3", "chunk-003", "Content about Keboola orchestration.")

    edge1 = _make_edge("e1", "Pipeline runs nightly", ["ep-1"])
    edge2 = _make_edge("e2", "Snowflake is the warehouse", ["ep-2"])
    edge3 = _make_edge("e3", "Orchestration manages jobs", ["ep-3"])

    search_results = _make_search_results(
        edges=[edge1, edge2, edge3],
        edge_scores=[0.95, 0.72, 0.58],
    )

    mock_graphiti = AsyncMock()
    mock_graphiti.search_ = AsyncMock(return_value=search_results)
    mock_graphiti.driver = AsyncMock()
    mock_graphiti.driver.execute_query = AsyncMock(return_value=(
        [
            {"uuid": "ep-1", "name": "chunk-001", "content": "Content about data pipelines and ETL processes.", "source_desc": _make_episode_metadata("chunk-001")},
            {"uuid": "ep-2", "name": "chunk-002", "content": "Content about Snowflake warehousing.", "source_desc": _make_episode_metadata("chunk-002")},
            {"uuid": "ep-3", "name": "chunk-003", "content": "Content about Keboola orchestration.", "source_desc": _make_episode_metadata("chunk-003")},
        ],
        None,
        None,
    ))

    retriever._graphiti = mock_graphiti

    results = await retriever.search_chunks("data pipeline", num_results=10)

    assert len(results) == 3
    scores = [r.score for r in results]
    # Scores should be the RRF values, not all 1.0
    assert scores[0] == pytest.approx(0.95)
    assert scores[1] == pytest.approx(0.72)
    assert scores[2] == pytest.approx(0.58)
    # Sorted descending
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_search_chunks_includes_episode_results(retriever):
    """search_chunks() should include episode (BM25) results with their own RRF scores."""
    ep1 = _make_episode("ep-1", "chunk-010", "Episode content about monitoring and alerts.")

    # No edges, only episodes
    search_results = _make_search_results(
        edges=[],
        edge_scores=[],
        episodes=[ep1],
        episode_scores=[0.88],
    )

    mock_graphiti = AsyncMock()
    mock_graphiti.search_ = AsyncMock(return_value=search_results)
    mock_graphiti.driver = AsyncMock()
    mock_graphiti.driver.execute_query = AsyncMock(return_value=(
        [
            {"uuid": "ep-1", "name": "chunk-010", "content": "Episode content about monitoring and alerts.", "source_desc": _make_episode_metadata("chunk-010")},
        ],
        None,
        None,
    ))

    retriever._graphiti = mock_graphiti

    results = await retriever.search_chunks("monitoring alerts", num_results=5)

    assert len(results) == 1
    assert results[0].score == pytest.approx(0.88)
    assert "monitoring" in results[0].content.lower()


@pytest.mark.asyncio
async def test_search_chunks_merges_edges_and_episodes(retriever):
    """Edges and episodes should be merged and sorted by score descending."""
    ep_edge = _make_episode("ep-edge", "chunk-e1", "Edge episode content here for testing.")
    ep_direct = _make_episode("ep-direct", "chunk-d1", "Direct episode content about search quality improvements.")

    edge = _make_edge("e1", "Search uses HNSW", ["ep-edge"])

    search_results = _make_search_results(
        edges=[edge],
        edge_scores=[0.60],
        episodes=[ep_direct],
        episode_scores=[0.85],
    )

    mock_graphiti = AsyncMock()
    mock_graphiti.search_ = AsyncMock(return_value=search_results)
    mock_graphiti.driver = AsyncMock()
    mock_graphiti.driver.execute_query = AsyncMock(return_value=(
        [
            {"uuid": "ep-edge", "name": "chunk-e1", "content": "Edge episode content here for testing.", "source_desc": _make_episode_metadata("chunk-e1")},
            {"uuid": "ep-direct", "name": "chunk-d1", "content": "Direct episode content about search quality improvements.", "source_desc": _make_episode_metadata("chunk-d1")},
        ],
        None,
        None,
    ))

    retriever._graphiti = mock_graphiti

    results = await retriever.search_chunks("search quality", num_results=10)

    assert len(results) == 2
    # Episode result (0.85) should be ranked above edge result (0.60)
    assert results[0].score == pytest.approx(0.85)
    assert results[1].score == pytest.approx(0.60)


@pytest.mark.asyncio
async def test_search_chunks_deduplicates_episode_across_edge_and_episode(retriever):
    """An episode already seen via an edge should not appear again as a direct episode result."""
    ep1 = _make_episode("ep-shared", "chunk-shared", "Shared episode content about deployment processes.")

    edge = _make_edge("e1", "Deploy runs on Cloud Run", ["ep-shared"])

    # Same episode appears in both edges and episodes
    search_results = _make_search_results(
        edges=[edge],
        edge_scores=[0.90],
        episodes=[ep1],
        episode_scores=[0.75],
    )

    mock_graphiti = AsyncMock()
    mock_graphiti.search_ = AsyncMock(return_value=search_results)
    mock_graphiti.driver = AsyncMock()
    mock_graphiti.driver.execute_query = AsyncMock(return_value=(
        [
            {"uuid": "ep-shared", "name": "chunk-shared", "content": "Shared episode content about deployment processes.", "source_desc": _make_episode_metadata("chunk-shared")},
        ],
        None,
        None,
    ))

    retriever._graphiti = mock_graphiti

    results = await retriever.search_chunks("deployment", num_results=10)

    # Should only have 1 result (deduplicated)
    assert len(results) == 1
    assert results[0].score == pytest.approx(0.90)


@pytest.mark.asyncio
async def test_search_chunks_empty_results(retriever):
    """search_chunks() should return empty list when search_ returns nothing."""
    search_results = _make_search_results()

    mock_graphiti = AsyncMock()
    mock_graphiti.search_ = AsyncMock(return_value=search_results)

    retriever._graphiti = mock_graphiti

    results = await retriever.search_chunks("nonexistent topic", num_results=5)

    assert results == []


@pytest.mark.asyncio
async def test_to_search_result_explicit_score():
    """_to_search_result() should use explicit score when provided."""
    with patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client") as mock_client:
        mock_client.return_value = MagicMock()
        retriever = GraphitiRetriever(group_id="test")

    mock_result = MagicMock()
    mock_result.score = 0.5  # This should be overridden
    mock_result.fact = None
    mock_result.source_description = json.dumps({"chunk_id": "c1"})
    mock_result.content = "Test content that is long enough"
    mock_result.name = "c1"

    sr = retriever._to_search_result(mock_result, score=0.99)
    assert sr.score == pytest.approx(0.99)

    # Without explicit score, should fall back to result attribute
    sr2 = retriever._to_search_result(mock_result)
    assert sr2.score == pytest.approx(0.5)
