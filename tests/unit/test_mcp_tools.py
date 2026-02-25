"""Tests for MCP tool definitions and execution dispatcher."""

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent

from knowledge_base.mcp.tools import (
    TOOLS,
    _apply_filters,
    execute_tool,
    get_tools_for_scopes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeSearchResult:
    """Minimal stand-in for SearchResult used in tool execution tests."""

    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any]

    @property
    def page_title(self) -> str:
        return self.metadata.get("page_title", "")


def _make_result(
    chunk_id: str = "c1",
    content: str = "some content",
    score: float = 0.9,
    page_title: str = "My Page",
    url: str = "https://example.com",
    space_key: str = "ENG",
    doc_type: str = "webpage",
    topics: list[str] | None = None,
    updated_at: str = "2026-01-15T00:00:00Z",
) -> _FakeSearchResult:
    return _FakeSearchResult(
        chunk_id=chunk_id,
        content=content,
        score=score,
        metadata={
            "page_title": page_title,
            "url": url,
            "space_key": space_key,
            "doc_type": doc_type,
            "topics": json.dumps(topics or []),
            "updated_at": updated_at,
        },
    )


_USER_INTERNAL = {"email": "alice@keboola.com", "scopes": ["kb.read", "kb.write"]}
_USER_EXTERNAL = {"email": "bob@external.com", "scopes": ["kb.read"]}


# ===========================================================================
# get_tools_for_scopes
# ===========================================================================


class TestGetToolsForScopes:
    """Test scope-based tool filtering."""

    def test_read_scopes_return_read_tools(self):
        """kb.read should return ask_question, search_knowledge, check_health."""
        tools = get_tools_for_scopes(["kb.read"])
        names = {t.name for t in tools}
        assert names == {"ask_question", "search_knowledge", "check_health"}

    def test_write_scopes_return_write_tools(self):
        """kb.write should return create_knowledge, ingest_document, submit_feedback."""
        tools = get_tools_for_scopes(["kb.write"])
        names = {t.name for t in tools}
        assert names == {"create_knowledge", "ingest_document", "submit_feedback"}

    def test_both_scopes_return_all_tools(self):
        """kb.read + kb.write should return all 6 tools."""
        tools = get_tools_for_scopes(["kb.read", "kb.write"])
        names = {t.name for t in tools}
        assert len(names) == 6
        assert names == {
            "ask_question",
            "search_knowledge",
            "check_health",
            "create_knowledge",
            "ingest_document",
            "submit_feedback",
        }

    def test_empty_scopes_return_no_tools(self):
        """Empty scope list should return no tools."""
        tools = get_tools_for_scopes([])
        assert tools == []

    def test_irrelevant_scopes_return_no_tools(self):
        """Scopes like openid/email should not grant access to any tools."""
        tools = get_tools_for_scopes(["openid", "email", "profile"])
        assert tools == []

    def test_returned_tools_are_tool_instances(self):
        """Each returned item should be a Tool with name and inputSchema."""
        tools = get_tools_for_scopes(["kb.read"])
        for tool in tools:
            assert hasattr(tool, "name")
            assert hasattr(tool, "inputSchema")

    def test_tool_definitions_count(self):
        """TOOLS list should contain exactly 6 tool definitions."""
        assert len(TOOLS) == 6


# ===========================================================================
# _apply_filters
# ===========================================================================


class TestApplyFilters:
    """Test metadata-based filtering of search results."""

    def test_no_filters_returns_all(self):
        """Empty filter dict returns all results unchanged."""
        results = [_make_result(chunk_id="c1"), _make_result(chunk_id="c2")]
        filtered = _apply_filters(results, {})
        assert len(filtered) == 2

    def test_space_key_filter(self):
        """Filter by space_key keeps only matching results."""
        results = [
            _make_result(chunk_id="c1", space_key="ENG"),
            _make_result(chunk_id="c2", space_key="SALES"),
        ]
        filtered = _apply_filters(results, {"space_key": "ENG"})
        assert len(filtered) == 1
        assert filtered[0].chunk_id == "c1"

    def test_doc_type_filter(self):
        """Filter by doc_type keeps only matching results."""
        results = [
            _make_result(chunk_id="c1", doc_type="webpage"),
            _make_result(chunk_id="c2", doc_type="pdf"),
            _make_result(chunk_id="c3", doc_type="quick_fact"),
        ]
        filtered = _apply_filters(results, {"doc_type": "pdf"})
        assert len(filtered) == 1
        assert filtered[0].chunk_id == "c2"

    def test_topics_filter_json_array(self):
        """Filter by topics works with JSON-encoded topic arrays."""
        results = [
            _make_result(chunk_id="c1", topics=["deployment", "ci"]),
            _make_result(chunk_id="c2", topics=["billing"]),
            _make_result(chunk_id="c3", topics=["deployment", "security"]),
        ]
        filtered = _apply_filters(results, {"topics": ["deployment"]})
        assert len(filtered) == 2
        ids = {r.chunk_id for r in filtered}
        assert ids == {"c1", "c3"}

    def test_topics_filter_string_fallback(self):
        """When topics is a plain string (not JSON), treat it as a single-element list."""
        result = _FakeSearchResult(
            chunk_id="c1",
            content="text",
            score=0.5,
            metadata={"topics": "security"},
        )
        filtered = _apply_filters([result], {"topics": ["security"]})
        assert len(filtered) == 1

    def test_topics_filter_no_match(self):
        """If none of the requested topics match, the result is excluded."""
        results = [_make_result(chunk_id="c1", topics=["billing"])]
        filtered = _apply_filters(results, {"topics": ["deployment"]})
        assert len(filtered) == 0

    def test_updated_after_filter(self):
        """Filter by updated_after keeps only results updated after the date."""
        results = [
            _make_result(chunk_id="c1", updated_at="2026-01-01T00:00:00Z"),
            _make_result(chunk_id="c2", updated_at="2026-02-01T00:00:00Z"),
        ]
        filtered = _apply_filters(results, {"updated_after": "2026-01-15T00:00:00Z"})
        assert len(filtered) == 1
        assert filtered[0].chunk_id == "c2"

    def test_combined_filters(self):
        """Multiple filters are applied together (AND logic)."""
        results = [
            _make_result(chunk_id="c1", space_key="ENG", doc_type="webpage"),
            _make_result(chunk_id="c2", space_key="ENG", doc_type="pdf"),
            _make_result(chunk_id="c3", space_key="SALES", doc_type="webpage"),
        ]
        filtered = _apply_filters(results, {"space_key": "ENG", "doc_type": "webpage"})
        assert len(filtered) == 1
        assert filtered[0].chunk_id == "c1"

    def test_filter_result_with_no_metadata(self):
        """Results without metadata attribute should not crash."""
        result = MagicMock(spec=[])  # no attributes at all
        # _apply_filters checks hasattr(r, "metadata")
        filtered = _apply_filters([result], {"space_key": "ENG"})
        # Without metadata, space_key check against {} will fail -> excluded
        assert len(filtered) == 0


# ===========================================================================
# execute_tool
# ===========================================================================


class TestExecuteToolAskQuestion:
    """Test ask_question tool execution."""

    async def test_ask_question_returns_text_content(self):
        """ask_question should return a list of TextContent with the answer and sources."""
        fake_chunks = [
            _make_result(
                chunk_id="c1",
                content="Keboola is a data platform.",
                page_title="About Keboola",
                url="https://wiki.keboola.com/about",
            ),
        ]
        with (
            patch(
                "knowledge_base.core.qa.search_knowledge",
                new_callable=AsyncMock,
                return_value=fake_chunks,
            ),
            patch(
                "knowledge_base.core.qa.generate_answer",
                new_callable=AsyncMock,
                return_value="Keboola is a data platform.",
            ),
        ):
            result = await execute_tool(
                "ask_question",
                {"question": "What is Keboola?"},
                _USER_INTERNAL,
            )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Keboola is a data platform." in result[0].text
        assert "Sources:" in result[0].text
        assert "About Keboola" in result[0].text

    async def test_ask_question_no_sources(self):
        """When search returns no chunks, sources section is absent."""
        with (
            patch(
                "knowledge_base.core.qa.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "knowledge_base.core.qa.generate_answer",
                new_callable=AsyncMock,
                return_value="No information found.",
            ),
        ):
            result = await execute_tool(
                "ask_question",
                {"question": "Something obscure?"},
                _USER_INTERNAL,
            )

        assert len(result) == 1
        assert "Sources:" not in result[0].text

    async def test_ask_question_with_conversation_history(self):
        """Conversation history should be passed through to generate_answer."""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi, how can I help?"},
        ]
        mock_generate = AsyncMock(return_value="Follow-up answer.")
        with (
            patch(
                "knowledge_base.core.qa.search_knowledge",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "knowledge_base.core.qa.generate_answer",
                mock_generate,
            ),
        ):
            await execute_tool(
                "ask_question",
                {"question": "Follow-up?", "conversation_history": history},
                _USER_INTERNAL,
            )

        # generate_answer should have been called with conversation_history
        mock_generate.assert_called_once()
        call_kwargs = mock_generate.call_args
        assert call_kwargs[0][2] == history  # third positional arg


class TestExecuteToolSearchKnowledge:
    """Test search_knowledge tool execution."""

    async def test_search_returns_formatted_results(self):
        """search_knowledge should return formatted markdown-like results."""
        fake_results = [
            _make_result(
                chunk_id="c1",
                content="First result content",
                score=0.95,
                page_title="Page One",
                url="https://wiki.keboola.com/page1",
            ),
            _make_result(
                chunk_id="c2",
                content="Second result content",
                score=0.85,
                page_title="Page Two",
                url="https://wiki.keboola.com/page2",
            ),
        ]
        with patch(
            "knowledge_base.core.qa.search_knowledge",
            new_callable=AsyncMock,
            return_value=fake_results,
        ):
            result = await execute_tool(
                "search_knowledge",
                {"query": "test query"},
                _USER_INTERNAL,
            )

        assert len(result) == 1
        text = result[0].text
        assert "Found 2 results" in text
        assert "Page One" in text
        assert "Page Two" in text
        assert "0.950" in text
        assert "c1" in text

    async def test_search_no_results(self):
        """When no results found, return appropriate message."""
        with patch(
            "knowledge_base.core.qa.search_knowledge",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await execute_tool(
                "search_knowledge",
                {"query": "nonexistent stuff"},
                _USER_INTERNAL,
            )

        assert len(result) == 1
        assert "No results found" in result[0].text

    async def test_search_respects_top_k(self):
        """top_k limits the number of returned results."""
        many_results = [_make_result(chunk_id=f"c{i}") for i in range(10)]
        with patch(
            "knowledge_base.core.qa.search_knowledge",
            new_callable=AsyncMock,
            return_value=many_results,
        ):
            result = await execute_tool(
                "search_knowledge",
                {"query": "test", "top_k": 3},
                _USER_INTERNAL,
            )

        text = result[0].text
        assert "Found 3 results" in text


class TestExecuteToolCreateKnowledge:
    """Test create_knowledge tool execution."""

    async def test_create_knowledge_success(self):
        """create_knowledge should index a chunk and return confirmation."""
        mock_indexer = AsyncMock()
        mock_indexer.index_single_chunk = AsyncMock()

        with patch(
            "knowledge_base.graph.graphiti_indexer.GraphitiIndexer",
            return_value=mock_indexer,
        ):
            result = await execute_tool(
                "create_knowledge",
                {"content": "Neo4j is a graph database.", "topics": ["databases", "graphs"]},
                _USER_INTERNAL,
            )

        assert len(result) == 1
        text = result[0].text
        assert "Knowledge saved successfully" in text
        assert "Neo4j is a graph database." in text
        mock_indexer.index_single_chunk.assert_called_once()

        # Verify the ChunkData passed to the indexer
        chunk_data = mock_indexer.index_single_chunk.call_args[0][0]
        assert chunk_data.content == "Neo4j is a graph database."
        assert chunk_data.space_key == "MCP"
        assert chunk_data.doc_type == "quick_fact"
        assert "alice@keboola.com" in chunk_data.page_title

    async def test_create_knowledge_default_topics(self):
        """create_knowledge without topics should use empty list."""
        mock_indexer = AsyncMock()
        mock_indexer.index_single_chunk = AsyncMock()

        with patch(
            "knowledge_base.graph.graphiti_indexer.GraphitiIndexer",
            return_value=mock_indexer,
        ):
            await execute_tool(
                "create_knowledge",
                {"content": "A fact."},
                _USER_INTERNAL,
            )

        chunk_data = mock_indexer.index_single_chunk.call_args[0][0]
        assert chunk_data.topics == "[]"


class TestExecuteToolSubmitFeedback:
    """Test submit_feedback tool execution."""

    async def test_submit_feedback_success(self):
        """submit_feedback should call lifecycle.feedback.submit_feedback."""
        mock_feedback = MagicMock()
        mock_feedback.id = 42

        with patch(
            "knowledge_base.lifecycle.feedback.submit_feedback",
            new_callable=AsyncMock,
            return_value=mock_feedback,
        ):
            result = await execute_tool(
                "submit_feedback",
                {"chunk_id": "c123", "feedback_type": "helpful", "details": "Great content!"},
                _USER_INTERNAL,
            )

        assert len(result) == 1
        text = result[0].text
        assert "Feedback submitted" in text
        assert "c123" in text
        assert "helpful" in text
        assert "42" in text

    async def test_submit_feedback_without_details(self):
        """submit_feedback should work without optional details."""
        mock_feedback = MagicMock()
        mock_feedback.id = 7

        with patch(
            "knowledge_base.lifecycle.feedback.submit_feedback",
            new_callable=AsyncMock,
            return_value=mock_feedback,
        ):
            result = await execute_tool(
                "submit_feedback",
                {"chunk_id": "c999", "feedback_type": "outdated"},
                _USER_INTERNAL,
            )

        assert "Feedback submitted" in result[0].text


class TestExecuteToolCheckHealth:
    """Test check_health tool execution."""

    async def test_check_health_healthy(self):
        """check_health should return healthy status when graphiti is up."""
        mock_retriever = AsyncMock()
        mock_retriever.check_health = AsyncMock(
            return_value={
                "graphiti_enabled": True,
                "graphiti_healthy": True,
                "backend": "graphiti",
            }
        )

        with patch(
            "knowledge_base.search.HybridRetriever",
            return_value=mock_retriever,
        ):
            result = await execute_tool("check_health", {}, _USER_INTERNAL)

        assert len(result) == 1
        text = result[0].text
        assert "healthy" in text
        assert "Graphiti enabled: True" in text
        assert "Graphiti healthy: True" in text

    async def test_check_health_degraded(self):
        """check_health should return degraded when graphiti is not healthy."""
        mock_retriever = AsyncMock()
        mock_retriever.check_health = AsyncMock(
            return_value={
                "graphiti_enabled": True,
                "graphiti_healthy": False,
                "backend": "graphiti",
            }
        )

        with patch(
            "knowledge_base.search.HybridRetriever",
            return_value=mock_retriever,
        ):
            result = await execute_tool("check_health", {}, _USER_INTERNAL)

        text = result[0].text
        assert "degraded" in text


class TestExecuteToolUnknown:
    """Test unknown tool execution and error handling."""

    async def test_unknown_tool_returns_error(self):
        """Unknown tool name should return an error TextContent."""
        result = await execute_tool("nonexistent_tool", {}, _USER_INTERNAL)
        assert len(result) == 1
        assert "Unknown tool: nonexistent_tool" in result[0].text

    async def test_tool_execution_exception_returns_error(self):
        """If a tool raises an exception, it should be caught and returned as text."""
        with patch(
            "knowledge_base.core.qa.search_knowledge",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection lost"),
        ):
            result = await execute_tool(
                "ask_question",
                {"question": "test"},
                _USER_INTERNAL,
            )

        assert len(result) == 1
        assert "Error executing ask_question" in result[0].text
        assert "connection lost" in result[0].text
