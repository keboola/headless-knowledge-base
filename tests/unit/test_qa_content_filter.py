"""Tests for defensive content filtering in generate_answer().

Verifies that generate_answer():
1. Filters out chunks with empty/whitespace-only content before sending to LLM
2. Returns "no info" message when all chunks have empty content
3. Falls back to URL when page_title is missing in Source headers
4. Falls back to "Chunk {chunk_id}" when both page_title and URL are missing
"""

import pytest
from unittest.mock import AsyncMock, patch

from knowledge_base.core.qa import generate_answer
from knowledge_base.search.models import SearchResult


_SENTINEL = object()


def _make_chunk(
    chunk_id: str = "c1",
    content: str = "Long enough content for testing purposes here",
    score: float = 0.9,
    metadata: dict | object = _SENTINEL,
) -> SearchResult:
    if metadata is _SENTINEL:
        metadata = {"page_title": "Test Page"}
    return SearchResult(
        chunk_id=chunk_id,
        content=content,
        score=score,
        metadata=metadata,
    )


@patch("knowledge_base.core.qa.get_llm")
@pytest.mark.asyncio
async def test_empty_content_chunks_excluded_from_llm_context(mock_get_llm):
    """Chunks with empty or whitespace-only content must not appear in the LLM prompt."""
    mock_llm = AsyncMock()
    mock_llm.provider_name = "test"
    mock_llm.generate = AsyncMock(return_value="Test answer")
    mock_get_llm.return_value = mock_llm

    chunks = [
        _make_chunk(chunk_id="good1", content="Real content about deployments"),
        _make_chunk(chunk_id="empty1", content=""),
        _make_chunk(chunk_id="empty2", content="   \n\t  "),
    ]

    result = await generate_answer("How do deployments work?", chunks)

    assert result == "Test answer"
    mock_llm.generate.assert_awaited_once()

    prompt = mock_llm.generate.call_args[0][0]
    assert "[Source 1: Test Page]" in prompt
    assert "Real content about deployments" in prompt
    # Only 1 source should be present -- the two empty chunks must be filtered out
    assert "[Source 2:" not in prompt
    assert "[Source 3:" not in prompt


@pytest.mark.asyncio
async def test_all_empty_chunks_returns_no_info_message():
    """When every chunk has empty content, return the no-info message without calling LLM."""
    chunks = [
        _make_chunk(chunk_id="e1", content=""),
        _make_chunk(chunk_id="e2", content="   "),
        _make_chunk(chunk_id="e3", content="\n\t"),
    ]

    result = await generate_answer("What is X?", chunks)

    assert result == "I couldn't find relevant information in the knowledge base to answer your question."


@patch("knowledge_base.core.qa.get_llm")
@pytest.mark.asyncio
async def test_title_fallback_to_url(mock_get_llm):
    """When page_title is missing, the Source header should use the chunk's URL."""
    mock_llm = AsyncMock()
    mock_llm.provider_name = "test"
    mock_llm.generate = AsyncMock(return_value="Answer using URL source")
    mock_get_llm.return_value = mock_llm

    chunks = [
        _make_chunk(
            chunk_id="u1",
            content="Content about networking",
            metadata={"url": "https://wiki.example.com/networking"},
        ),
    ]

    await generate_answer("Tell me about networking", chunks)

    prompt = mock_llm.generate.call_args[0][0]
    assert "[Source 1: https://wiki.example.com/networking]" in prompt


@patch("knowledge_base.core.qa.get_llm")
@pytest.mark.asyncio
async def test_title_fallback_to_chunk_id(mock_get_llm):
    """When both page_title and URL are missing, the Source header should use 'Chunk {chunk_id}'."""
    mock_llm = AsyncMock()
    mock_llm.provider_name = "test"
    mock_llm.generate = AsyncMock(return_value="Answer using chunk id source")
    mock_get_llm.return_value = mock_llm

    chunks = [
        _make_chunk(
            chunk_id="abc-123",
            content="Content about something",
            metadata={},
        ),
    ]

    await generate_answer("What is something?", chunks)

    prompt = mock_llm.generate.call_args[0][0]
    assert "[Source 1: Chunk abc-123]" in prompt
