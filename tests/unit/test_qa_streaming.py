"""Tests for streaming Q&A and quick answer generation in core/qa.py."""

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.core.qa import (
    _NO_CHUNKS_MESSAGE,
    _build_answer_prompt,
    generate_answer_stream,
    generate_quick_answer,
)
from knowledge_base.search import SearchResult


def _make_chunk(
    chunk_id: str = "c1",
    content: str = "Some helpful content about the topic.",
    page_title: str = "Test Page",
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        content=content,
        score=0.9,
        metadata={
            "page_title": page_title,
            "url": f"https://example.com/{chunk_id}",
        },
    )


# ---------------------------------------------------------------------------
# _build_answer_prompt
# ---------------------------------------------------------------------------


class TestBuildAnswerPrompt:
    def test_returns_none_when_no_chunks(self) -> None:
        assert _build_answer_prompt("question", []) is None

    def test_returns_none_when_chunks_have_empty_content(self) -> None:
        chunks = [_make_chunk(content=""), _make_chunk(content="   ")]
        assert _build_answer_prompt("question", chunks) is None

    def test_includes_question_and_context(self) -> None:
        chunks = [_make_chunk(content="The sky is blue.", page_title="Sky Facts")]
        prompt = _build_answer_prompt("Why is the sky blue?", chunks)
        assert prompt is not None
        assert "Why is the sky blue?" in prompt
        assert "The sky is blue." in prompt
        assert "Sky Facts" in prompt

    def test_includes_conversation_history(self) -> None:
        chunks = [_make_chunk()]
        history = [
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
        ]
        prompt = _build_answer_prompt("Follow-up?", chunks, history)
        assert prompt is not None
        assert "PREVIOUS CONVERSATION" in prompt
        assert "Earlier question" in prompt
        assert "Earlier answer" in prompt

    def test_truncates_long_history_messages(self) -> None:
        chunks = [_make_chunk()]
        history = [{"role": "user", "content": "x" * 1000}]
        prompt = _build_answer_prompt("q", chunks, history)
        assert prompt is not None
        # Truncated to 500 + "..." -> should not contain full 1000-char content
        assert "x" * 1000 not in prompt
        assert "..." in prompt


# ---------------------------------------------------------------------------
# generate_answer_stream
# ---------------------------------------------------------------------------


class TestGenerateAnswerStream:
    @pytest.mark.asyncio
    async def test_yields_no_chunks_message_when_chunks_empty(self) -> None:
        outputs = []
        async for fragment in generate_answer_stream("q", []):
            outputs.append(fragment)
        assert outputs == [_NO_CHUNKS_MESSAGE]

    @pytest.mark.asyncio
    async def test_streams_llm_tokens(self) -> None:
        chunks = [_make_chunk(content="Useful information.")]

        async def fake_stream(prompt: str, **kwargs):
            for fragment in ["Hello ", "from ", "the LLM."]:
                yield fragment

        mock_llm = MagicMock()
        mock_llm.provider_name = "test"
        mock_llm.generate_stream = fake_stream

        with patch("knowledge_base.core.qa.get_llm", AsyncMock(return_value=mock_llm)):
            outputs = []
            async for fragment in generate_answer_stream("q", chunks):
                outputs.append(fragment)

        assert outputs == ["Hello ", "from ", "the LLM."]

    @pytest.mark.asyncio
    async def test_yields_friendly_error_on_llm_failure(self) -> None:
        chunks = [_make_chunk(content="Useful information."), _make_chunk(chunk_id="c2")]

        async def failing_stream(prompt: str, **kwargs):
            if False:
                yield ""  # make this an async generator
            raise RuntimeError("boom")

        mock_llm = MagicMock()
        mock_llm.provider_name = "test"
        mock_llm.generate_stream = failing_stream

        with patch("knowledge_base.core.qa.get_llm", AsyncMock(return_value=mock_llm)):
            outputs = []
            async for fragment in generate_answer_stream("q", chunks):
                outputs.append(fragment)

        assert len(outputs) == 1
        assert "couldn't generate" in outputs[0]
        assert "2 relevant documents" in outputs[0]


# ---------------------------------------------------------------------------
# generate_quick_answer
# ---------------------------------------------------------------------------


class TestGenerateQuickAnswer:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_chunks(self) -> None:
        result = await generate_quick_answer("q", [])
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_when_chunks_have_no_content(self) -> None:
        chunks = [_make_chunk(content=""), _make_chunk(content="  ")]
        result = await generate_quick_answer("q", chunks)
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_llm_answer_stripped(self) -> None:
        chunks = [_make_chunk(content="Real content.")]
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="  The quick answer.  \n")

        with patch("knowledge_base.core.qa.get_llm", AsyncMock(return_value=mock_llm)):
            result = await generate_quick_answer("q", chunks)

        assert result == "The quick answer."
        # Verify max_output_tokens was passed to keep it small
        mock_llm.generate.assert_called_once()
        kwargs = mock_llm.generate.call_args.kwargs
        assert "max_output_tokens" in kwargs
        assert kwargs["max_output_tokens"] > 0

    @pytest.mark.asyncio
    async def test_respects_explicit_max_tokens(self) -> None:
        chunks = [_make_chunk(content="Real content.")]
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="Quick.")

        with patch("knowledge_base.core.qa.get_llm", AsyncMock(return_value=mock_llm)):
            await generate_quick_answer("q", chunks, max_tokens=42)

        kwargs = mock_llm.generate.call_args.kwargs
        assert kwargs["max_output_tokens"] == 42

    @pytest.mark.asyncio
    async def test_uses_only_top_3_chunks(self) -> None:
        chunks = [_make_chunk(chunk_id=f"c{i}", content=f"Content {i}") for i in range(10)]
        captured_prompt = ""

        async def capture_generate(prompt, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "answer"

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=capture_generate)

        with patch("knowledge_base.core.qa.get_llm", AsyncMock(return_value=mock_llm)):
            await generate_quick_answer("q", chunks)

        # Expect content from chunks 0-2, NOT from chunks 3-9
        assert "Content 0" in captured_prompt
        assert "Content 1" in captured_prompt
        assert "Content 2" in captured_prompt
        assert "Content 3" not in captured_prompt
        assert "Content 9" not in captured_prompt

    @pytest.mark.asyncio
    async def test_returns_empty_string_on_failure(self) -> None:
        chunks = [_make_chunk(content="Real content.")]
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("knowledge_base.core.qa.get_llm", AsyncMock(return_value=mock_llm)):
            result = await generate_quick_answer("q", chunks)

        assert result == ""


# ---------------------------------------------------------------------------
# BaseLLM default streaming behavior
# ---------------------------------------------------------------------------


class TestBaseLLMStreamFallback:
    @pytest.mark.asyncio
    async def test_default_stream_yields_full_result(self) -> None:
        """Providers that don't override generate_stream() fall back to generate()."""
        from knowledge_base.rag.llm import BaseLLM

        class FakeLLM(BaseLLM):
            @property
            def provider_name(self) -> str:
                return "fake"

            async def generate(self, prompt: str, **kwargs) -> str:
                return "full answer"

            async def generate_json(self, prompt: str, **kwargs) -> dict:
                return {}

            async def check_health(self) -> bool:
                return True

        llm = FakeLLM()
        outputs = [chunk async for chunk in llm.generate_stream("q")]
        assert outputs == ["full answer"]
