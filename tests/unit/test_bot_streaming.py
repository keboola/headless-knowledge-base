"""Tests for the streaming Slack bot flow in slack/bot.py."""

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.search.models import SearchResult
from knowledge_base.slack.bot import (
    _build_sources_block,
    _render_streaming_answer,
    _stream_answer_to_slack,
)


def _make_chunk(
    chunk_id: str = "c1",
    content: str = "Helpful content.",
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
# _build_sources_block
# ---------------------------------------------------------------------------


class TestBuildSourcesBlock:
    def test_returns_none_for_empty_chunks(self) -> None:
        assert _build_sources_block([]) is None

    def test_returns_none_when_no_titles(self) -> None:
        chunks = [_make_chunk(page_title=""), _make_chunk(chunk_id="c2", page_title="   ")]
        assert _build_sources_block(chunks) is None

    def test_dedupes_titles(self) -> None:
        chunks = [
            _make_chunk(chunk_id="a", page_title="Same Title"),
            _make_chunk(chunk_id="b", page_title="Same Title"),
            _make_chunk(chunk_id="c", page_title="Other"),
        ]
        block = _build_sources_block(chunks)
        assert block is not None
        text = block["elements"][0]["text"]
        # "Same Title" should appear once
        assert text.count("Same Title") == 1
        assert "Other" in text

    def test_caps_at_three_sources(self) -> None:
        chunks = [_make_chunk(chunk_id=f"c{i}", page_title=f"Title {i}") for i in range(10)]
        block = _build_sources_block(chunks)
        assert block is not None
        text = block["elements"][0]["text"]
        assert "Title 0" in text
        assert "Title 1" in text
        assert "Title 2" in text
        assert "Title 3" not in text


# ---------------------------------------------------------------------------
# _render_streaming_answer
# ---------------------------------------------------------------------------


class TestRenderStreamingAnswer:
    def test_quick_only_no_detail(self) -> None:
        fallback, blocks = _render_streaming_answer(
            quick="Yes you can.", detailed="", chunks=None, streaming=False
        )
        assert "Quick answer:" in fallback
        assert "Yes you can." in fallback
        assert blocks  # non-empty

    def test_streaming_indicator_appended(self) -> None:
        fallback, _ = _render_streaming_answer(
            quick="", detailed="Working...", chunks=None, streaming=True
        )
        assert "_(streaming...)_" in fallback

    def test_no_streaming_indicator_when_done(self) -> None:
        fallback, _ = _render_streaming_answer(
            quick="", detailed="Final answer.", chunks=None, streaming=False
        )
        assert "_(streaming...)_" not in fallback

    def test_appends_sources_block_at_end(self) -> None:
        chunks = [_make_chunk(page_title="My Page")]
        _, blocks = _render_streaming_answer(
            quick="", detailed="Answer.", chunks=chunks, streaming=False
        )
        assert blocks[-1]["type"] == "context"
        assert "My Page" in blocks[-1]["elements"][0]["text"]

    def test_no_sources_block_when_chunks_none(self) -> None:
        _, blocks = _render_streaming_answer(
            quick="", detailed="Answer.", chunks=None, streaming=False
        )
        assert all(b.get("type") != "context" for b in blocks)

    def test_handles_empty_state(self) -> None:
        fallback, blocks = _render_streaming_answer(
            quick="", detailed="", chunks=None, streaming=False
        )
        assert fallback  # non-empty fallback
        assert blocks  # non-empty blocks

    def test_long_answer_split_into_multiple_blocks(self) -> None:
        long_text = "x" * 10000
        _, blocks = _render_streaming_answer(
            quick="", detailed=long_text, chunks=None, streaming=False
        )
        # Should split into multiple section blocks (>1)
        section_blocks = [b for b in blocks if b.get("type") == "section"]
        assert len(section_blocks) > 1


# ---------------------------------------------------------------------------
# _stream_answer_to_slack
# ---------------------------------------------------------------------------


class _AsyncCall:
    """Helper that records all calls made via async_call so we can assert on them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, func, *args, **kwargs):
        # Identify which Slack method was called by name on the func mock
        name = getattr(func, "_mock_name", "") or getattr(func, "__name__", "fn")
        self.calls.append((name, kwargs))
        if hasattr(func, "return_value"):
            return func.return_value
        return {}


class TestStreamAnswerToSlack:
    @pytest.mark.asyncio
    async def test_full_flow_with_quick_answer_and_streaming(self) -> None:
        client = MagicMock()
        client.chat_update = MagicMock(name="chat_update", return_value={})
        client.chat_postMessage = MagicMock(name="chat_postMessage", return_value={})
        async_call = _AsyncCall()

        chunks = [_make_chunk(content="Real content.")]

        async def fake_stream(question, chunks_arg, history):
            for token in ["Hello ", "from ", "the LLM."]:
                yield token

        with (
            patch("knowledge_base.slack.bot.generate_quick_answer", AsyncMock(return_value="Q!")),
            patch("knowledge_base.slack.bot.generate_answer_stream", fake_stream),
            patch(
                "knowledge_base.slack.bot.settings.SLACK_STREAMING_UPDATE_INTERVAL", 0.0
            ),
            patch(
                "knowledge_base.slack.bot.settings.SLACK_QUICK_ANSWER_ENABLED", True
            ),
        ):
            answer = await _stream_answer_to_slack(
                client=client,
                channel="C1",
                thinking_ts="123.456",
                text="What is X?",
                chunks=chunks,
                conversation_history=None,
                async_call=async_call,
            )

        assert answer == "Hello from the LLM."

        # Should have at least: search-status update, quick-answer update,
        # at least one streaming update, and final update.  All chat_update.
        update_kwargs = [kw for name, kw in async_call.calls if name == "chat_update"]
        assert len(update_kwargs) >= 3
        # Final update should NOT contain streaming indicator.
        last = update_kwargs[-1]
        assert "_(streaming...)_" not in last["text"]
        # First update is the search-status text.
        assert "Found 1 sources" in update_kwargs[0]["text"]

    @pytest.mark.asyncio
    async def test_falls_back_when_streaming_fails_with_no_tokens(self) -> None:
        client = MagicMock()
        client.chat_update = MagicMock(name="chat_update", return_value={})
        client.chat_postMessage = MagicMock(name="chat_postMessage", return_value={})
        async_call = _AsyncCall()

        chunks = [_make_chunk(content="Real content.")]

        async def failing_stream(question, chunks_arg, history):
            if False:
                yield ""  # make it an async generator
            raise RuntimeError("stream broke")

        with (
            patch("knowledge_base.slack.bot.generate_quick_answer", AsyncMock(return_value="")),
            patch("knowledge_base.slack.bot.generate_answer_stream", failing_stream),
            patch(
                "knowledge_base.slack.bot.generate_answer",
                AsyncMock(return_value="Fallback answer."),
            ),
            patch(
                "knowledge_base.slack.bot.settings.SLACK_STREAMING_UPDATE_INTERVAL", 0.0
            ),
            patch(
                "knowledge_base.slack.bot.settings.SLACK_QUICK_ANSWER_ENABLED", False
            ),
        ):
            answer = await _stream_answer_to_slack(
                client=client,
                channel="C1",
                thinking_ts="t1",
                text="q",
                chunks=chunks,
                conversation_history=None,
                async_call=async_call,
            )

        assert answer == "Fallback answer."
        update_kwargs = [kw for name, kw in async_call.calls if name == "chat_update"]
        # Final update should contain the fallback answer
        assert any("Fallback answer." in kw.get("text", "") for kw in update_kwargs)

    @pytest.mark.asyncio
    async def test_quick_answer_skipped_when_too_short(self) -> None:
        """Short quick-answer (e.g. 'Keb' from Gemini 2.5 thinking-token bug) is dropped."""
        client = MagicMock()
        client.chat_update = MagicMock(name="chat_update", return_value={})
        async_call = _AsyncCall()

        chunks = [_make_chunk()]

        async def fake_stream(question, chunks_arg, history):
            yield "Detailed answer here."

        with (
            patch("knowledge_base.slack.bot.generate_quick_answer", AsyncMock(return_value="Keb")),
            patch("knowledge_base.slack.bot.generate_answer_stream", fake_stream),
            patch("knowledge_base.slack.bot.settings.SLACK_STREAMING_UPDATE_INTERVAL", 0.0),
            patch("knowledge_base.slack.bot.settings.SLACK_QUICK_ANSWER_ENABLED", True),
            patch("knowledge_base.slack.bot.settings.SLACK_QUICK_ANSWER_MIN_LENGTH", 20),
        ):
            await _stream_answer_to_slack(
                client=client,
                channel="C1",
                thinking_ts="t1",
                text="q",
                chunks=chunks,
                conversation_history=None,
                async_call=async_call,
            )

        # No chat.update should contain "Quick answer: Keb"
        update_kwargs = [kw for name, kw in async_call.calls if name == "chat_update"]
        assert all("Quick answer:" not in kw.get("text", "") for kw in update_kwargs)

    @pytest.mark.asyncio
    async def test_quick_answer_skipped_when_disabled(self) -> None:
        client = MagicMock()
        client.chat_update = MagicMock(name="chat_update", return_value={})
        async_call = _AsyncCall()

        chunks = [_make_chunk()]

        async def fake_stream(question, chunks_arg, history):
            yield "Done."

        quick_mock = AsyncMock(return_value="should not appear")
        with (
            patch("knowledge_base.slack.bot.generate_quick_answer", quick_mock),
            patch("knowledge_base.slack.bot.generate_answer_stream", fake_stream),
            patch(
                "knowledge_base.slack.bot.settings.SLACK_STREAMING_UPDATE_INTERVAL", 0.0
            ),
            patch(
                "knowledge_base.slack.bot.settings.SLACK_QUICK_ANSWER_ENABLED", False
            ),
        ):
            await _stream_answer_to_slack(
                client=client,
                channel="C1",
                thinking_ts="t1",
                text="q",
                chunks=chunks,
                conversation_history=None,
                async_call=async_call,
            )

        # quick answer fn must not be called when feature flag is off
        quick_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_friendly_message_when_no_text_produced(self) -> None:
        client = MagicMock()
        client.chat_update = MagicMock(name="chat_update", return_value={})
        async_call = _AsyncCall()

        chunks = [_make_chunk()]

        async def empty_stream(question, chunks_arg, history):
            return
            yield ""  # never reached but makes it an async generator

        with (
            patch("knowledge_base.slack.bot.generate_quick_answer", AsyncMock(return_value="")),
            patch("knowledge_base.slack.bot.generate_answer_stream", empty_stream),
            patch(
                "knowledge_base.slack.bot.settings.SLACK_STREAMING_UPDATE_INTERVAL", 0.0
            ),
            patch(
                "knowledge_base.slack.bot.settings.SLACK_QUICK_ANSWER_ENABLED", False
            ),
        ):
            answer = await _stream_answer_to_slack(
                client=client,
                channel="C1",
                thinking_ts="t1",
                text="q",
                chunks=chunks,
                conversation_history=None,
                async_call=async_call,
            )

        assert "couldn't generate" in answer.lower()
