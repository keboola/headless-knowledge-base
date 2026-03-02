"""Tests for search_with_expansion and _deduplicate_results in core Q&A module."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from knowledge_base.core.qa import _deduplicate_results, search_with_expansion
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
    return SearchResult(
        chunk_id=chunk_id,
        content=content,
        score=score,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# _deduplicate_results tests
# ---------------------------------------------------------------------------


class TestDeduplicateResults:
    """Tests for _deduplicate_results."""

    def test_basic_dedup_keeps_highest_score(self) -> None:
        """Same chunk_id from different sets keeps the highest score."""
        set1 = [_make_result(chunk_id="c1", score=0.7)]
        set2 = [_make_result(chunk_id="c1", score=0.9)]

        result = _deduplicate_results([set1, set2], limit=10)

        assert len(result) == 1
        assert result[0].chunk_id == "c1"
        assert result[0].score == 0.9

    def test_results_sorted_by_score_descending(self) -> None:
        """Merged results are sorted by score from highest to lowest."""
        set1 = [
            _make_result(chunk_id="c1", score=0.5),
            _make_result(chunk_id="c2", score=0.9),
        ]
        set2 = [
            _make_result(chunk_id="c3", score=0.7),
        ]

        result = _deduplicate_results([set1, set2], limit=10)

        assert [r.chunk_id for r in result] == ["c2", "c3", "c1"]
        assert [r.score for r in result] == [0.9, 0.7, 0.5]

    def test_limit_respected(self) -> None:
        """Only the top-N results are returned when limit is smaller than total."""
        results = [_make_result(chunk_id=f"c{i}", score=1.0 - i * 0.1) for i in range(5)]

        merged = _deduplicate_results([results], limit=3)

        assert len(merged) == 3
        assert merged[0].score == 1.0
        assert merged[-1].score == 0.8

    def test_empty_input_returns_empty(self) -> None:
        """Empty list of result sets returns an empty list."""
        assert _deduplicate_results([], limit=10) == []

    def test_single_result_set_passthrough(self) -> None:
        """A single result set is returned sorted and limited."""
        results = [
            _make_result(chunk_id="c1", score=0.3),
            _make_result(chunk_id="c2", score=0.8),
        ]

        merged = _deduplicate_results([results], limit=10)

        assert len(merged) == 2
        assert merged[0].chunk_id == "c2"
        assert merged[1].chunk_id == "c1"

    def test_multiple_overlapping_result_sets_merge(self) -> None:
        """Multiple sets with partial overlap merge correctly."""
        set1 = [
            _make_result(chunk_id="c1", score=0.9),
            _make_result(chunk_id="c2", score=0.6),
        ]
        set2 = [
            _make_result(chunk_id="c2", score=0.8),  # higher score than set1
            _make_result(chunk_id="c3", score=0.7),
        ]
        set3 = [
            _make_result(chunk_id="c1", score=0.5),  # lower score than set1
            _make_result(chunk_id="c4", score=0.4),
        ]

        merged = _deduplicate_results([set1, set2, set3], limit=10)

        assert len(merged) == 4
        scores_by_id = {r.chunk_id: r.score for r in merged}
        assert scores_by_id["c1"] == 0.9  # kept from set1
        assert scores_by_id["c2"] == 0.8  # upgraded from set2
        assert scores_by_id["c3"] == 0.7
        assert scores_by_id["c4"] == 0.4
        # Verify sorted descending
        assert [r.score for r in merged] == [0.9, 0.8, 0.7, 0.4]


# ---------------------------------------------------------------------------
# search_with_expansion tests
# ---------------------------------------------------------------------------


class TestSearchWithExpansion:
    """Tests for search_with_expansion."""

    @pytest.mark.asyncio
    @patch("knowledge_base.core.qa.search_knowledge", new_callable=AsyncMock)
    @patch("knowledge_base.core.query_expansion.expand_query", new_callable=AsyncMock)
    @patch("knowledge_base.core.qa.settings")
    async def test_full_flow_expand_search_dedup(
        self,
        mock_settings: Any,
        mock_expand: AsyncMock,
        mock_search: AsyncMock,
    ) -> None:
        """Full flow: expand_query returns variants, searches all, deduplicates."""
        mock_settings.SEARCH_DEFAULT_LIMIT = 20
        mock_settings.SEARCH_QUERY_EXPANSION_ENABLED = True

        mock_expand.return_value = ["original query", "variant A", "variant B"]

        # Each search variant returns different results with some overlap
        mock_search.side_effect = [
            [_make_result(chunk_id="c1", score=0.9), _make_result(chunk_id="c2", score=0.6)],
            [_make_result(chunk_id="c2", score=0.8), _make_result(chunk_id="c3", score=0.7)],
            [_make_result(chunk_id="c4", score=0.5)],
        ]

        result = await search_with_expansion("original query")

        assert mock_expand.call_count == 1
        assert mock_search.call_count == 3
        assert len(result) == 4
        # c2 should have the higher score (0.8 from variant A, not 0.6 from original)
        scores_by_id = {r.chunk_id: r.score for r in result}
        assert scores_by_id["c2"] == 0.8

    @pytest.mark.asyncio
    @patch("knowledge_base.core.qa.search_knowledge", new_callable=AsyncMock)
    @patch("knowledge_base.core.qa.settings")
    async def test_feature_flag_disabled_falls_back(
        self,
        mock_settings: Any,
        mock_search: AsyncMock,
    ) -> None:
        """When SEARCH_QUERY_EXPANSION_ENABLED is False, falls back to single search."""
        mock_settings.SEARCH_DEFAULT_LIMIT = 10
        mock_settings.SEARCH_QUERY_EXPANSION_ENABLED = False

        expected = [_make_result(chunk_id="c1", score=0.9)]
        mock_search.return_value = expected

        result = await search_with_expansion("some query")

        mock_search.assert_called_once_with("some query", 10)
        assert result == expected

    @pytest.mark.asyncio
    @patch("knowledge_base.core.qa.search_knowledge", new_callable=AsyncMock)
    @patch("knowledge_base.core.query_expansion.expand_query", new_callable=AsyncMock)
    @patch("knowledge_base.core.qa.settings")
    async def test_expand_query_fails_falls_back(
        self,
        mock_settings: Any,
        mock_expand: AsyncMock,
        mock_search: AsyncMock,
    ) -> None:
        """When expand_query raises, falls back to single search_knowledge call."""
        mock_settings.SEARCH_DEFAULT_LIMIT = 10
        mock_settings.SEARCH_QUERY_EXPANSION_ENABLED = True

        mock_expand.side_effect = RuntimeError("LLM unavailable")
        expected = [_make_result(chunk_id="c1", score=0.8)]
        mock_search.return_value = expected

        result = await search_with_expansion("test query")

        # expand_query was attempted
        mock_expand.assert_called_once_with("test query")
        # Fallback to single search
        mock_search.assert_called_once_with("test query", 10)
        assert result == expected

    @pytest.mark.asyncio
    @patch("knowledge_base.core.qa.search_knowledge", new_callable=AsyncMock)
    @patch("knowledge_base.core.query_expansion.expand_query", new_callable=AsyncMock)
    @patch("knowledge_base.core.qa.settings")
    async def test_some_search_variants_fail(
        self,
        mock_settings: Any,
        mock_expand: AsyncMock,
        mock_search: AsyncMock,
    ) -> None:
        """When some search variants fail, results from successful ones are returned."""
        mock_settings.SEARCH_DEFAULT_LIMIT = 20
        mock_settings.SEARCH_QUERY_EXPANSION_ENABLED = True

        mock_expand.return_value = ["query A", "query B", "query C"]

        mock_search.side_effect = [
            [_make_result(chunk_id="c1", score=0.9)],
            RuntimeError("search failed"),
            [_make_result(chunk_id="c2", score=0.7)],
        ]

        result = await search_with_expansion("test query")

        assert len(result) == 2
        assert result[0].chunk_id == "c1"
        assert result[1].chunk_id == "c2"

    @pytest.mark.asyncio
    @patch("knowledge_base.core.qa.search_knowledge", new_callable=AsyncMock)
    @patch("knowledge_base.core.query_expansion.expand_query", new_callable=AsyncMock)
    @patch("knowledge_base.core.qa.settings")
    async def test_all_search_variants_fail_returns_empty(
        self,
        mock_settings: Any,
        mock_expand: AsyncMock,
        mock_search: AsyncMock,
    ) -> None:
        """When all search variants fail, returns an empty list."""
        mock_settings.SEARCH_DEFAULT_LIMIT = 20
        mock_settings.SEARCH_QUERY_EXPANSION_ENABLED = True

        mock_expand.return_value = ["query A", "query B"]
        mock_search.side_effect = [
            RuntimeError("search failed"),
            RuntimeError("search failed"),
        ]

        result = await search_with_expansion("test query")

        assert result == []

    @pytest.mark.asyncio
    @patch("knowledge_base.core.qa.search_knowledge", new_callable=AsyncMock)
    @patch("knowledge_base.core.query_expansion.expand_query", new_callable=AsyncMock)
    @patch("knowledge_base.core.qa.settings")
    async def test_custom_limit_respected(
        self,
        mock_settings: Any,
        mock_expand: AsyncMock,
        mock_search: AsyncMock,
    ) -> None:
        """Custom limit parameter is passed through and applied to final results."""
        mock_settings.SEARCH_DEFAULT_LIMIT = 20
        mock_settings.SEARCH_QUERY_EXPANSION_ENABLED = True

        mock_expand.return_value = ["query A", "query B"]

        # Each variant returns 3 results
        mock_search.side_effect = [
            [
                _make_result(chunk_id="c1", score=0.9),
                _make_result(chunk_id="c2", score=0.8),
                _make_result(chunk_id="c3", score=0.7),
            ],
            [
                _make_result(chunk_id="c4", score=0.6),
                _make_result(chunk_id="c5", score=0.5),
                _make_result(chunk_id="c6", score=0.4),
            ],
        ]

        result = await search_with_expansion("test query", limit=3)

        # Only top 3 results kept despite 6 unique results available
        assert len(result) == 3
        assert [r.chunk_id for r in result] == ["c1", "c2", "c3"]
        # Verify limit was passed to each search call
        for call in mock_search.call_args_list:
            assert call.kwargs.get("limit") == 3 or call[1].get("limit") == 3
