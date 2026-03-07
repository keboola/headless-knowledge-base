"""Tests for Slack bot source rendering logic.

Tests the source block construction that appears in bot.py _handle_question().
The logic is replicated here as a helper function to test in isolation without
needing to invoke the full async Slack handler.
"""

import pytest

from knowledge_base.search.models import SearchResult


def _make_result(chunk_id="chunk1", content="Some content", score=0.9, metadata=None):
    """Create a SearchResult with the given metadata."""
    return SearchResult(
        chunk_id=chunk_id,
        content=content,
        score=score,
        metadata=metadata or {},
    )


def _build_source_block(chunks):
    """Replicate the source rendering logic from bot.py for testing.

    This mirrors the exact code in _handle_question() (lines 564-583)
    so we can verify the rendering behavior without async dependencies.

    Returns the source context block dict or None if no sources.
    """
    if not chunks:
        return None
    source_lines = []
    seen_titles = set()
    for chunk in chunks:
        title = chunk.page_title
        if not title or not title.strip():
            continue
        if title in seen_titles:
            continue
        seen_titles.add(title)
        source_lines.append(f"\u2022 {title}")
        if len(source_lines) >= 3:
            break
    if source_lines:
        source_text = "*Sources:*\n" + "\n".join(source_lines)
        return {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": source_text}],
        }
    return None


class TestSourceRendering:
    """Test the source block rendering logic extracted from bot.py."""

    def test_empty_title_chunks_skipped(self):
        """Chunks with empty page_title should not appear in sources."""
        chunks = [
            _make_result(metadata={"page_title": ""}),
            _make_result(chunk_id="c2", metadata={"page_title": "Valid Title"}),
        ]
        block = _build_source_block(chunks)
        assert block is not None
        text = block["elements"][0]["text"]
        assert "Valid Title" in text
        # Should not have an empty bullet line
        assert "\u2022 \n" not in text

    def test_none_title_chunks_skipped(self):
        """Chunks with no page_title key produce no source block."""
        chunks = [_make_result(metadata={})]
        block = _build_source_block(chunks)
        assert block is None

    def test_whitespace_title_skipped(self):
        """Chunks with whitespace-only title produce no source block."""
        chunks = [_make_result(metadata={"page_title": "   "})]
        block = _build_source_block(chunks)
        assert block is None

    def test_duplicate_titles_deduplicated(self):
        """Multiple chunks from the same page should appear only once."""
        chunks = [
            _make_result(chunk_id="c1", metadata={"page_title": "Engineering Wiki"}),
            _make_result(chunk_id="c2", metadata={"page_title": "Engineering Wiki"}),
            _make_result(chunk_id="c3", metadata={"page_title": "HR Handbook"}),
        ]
        block = _build_source_block(chunks)
        assert block is not None
        text = block["elements"][0]["text"]
        assert text.count("Engineering Wiki") == 1
        assert "HR Handbook" in text

    def test_no_source_block_when_all_empty(self):
        """When ALL chunks have empty or missing titles, no block is produced."""
        chunks = [
            _make_result(chunk_id="c1", metadata={"page_title": ""}),
            _make_result(chunk_id="c2", metadata={}),
        ]
        block = _build_source_block(chunks)
        assert block is None

    def test_max_three_sources(self):
        """At most 3 source lines should be shown regardless of chunk count."""
        chunks = [
            _make_result(chunk_id=f"c{i}", metadata={"page_title": f"Doc {i}"})
            for i in range(10)
        ]
        block = _build_source_block(chunks)
        assert block is not None
        text = block["elements"][0]["text"]
        assert text.count("\u2022") == 3

    def test_no_chunks_returns_none(self):
        """An empty chunk list returns None (no source block)."""
        block = _build_source_block([])
        assert block is None

    def test_block_structure(self):
        """Verify the exact Slack block structure of a source block."""
        chunks = [
            _make_result(metadata={"page_title": "Getting Started Guide"}),
        ]
        block = _build_source_block(chunks)
        assert block == {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "*Sources:*\n\u2022 Getting Started Guide",
                }
            ],
        }

    def test_plain_text_titles_no_links(self):
        """Source lines use plain text titles, not Slack links or markdown."""
        chunks = [
            _make_result(
                metadata={
                    "page_title": "My Page",
                    "url": "https://example.com/page",
                }
            ),
        ]
        block = _build_source_block(chunks)
        text = block["elements"][0]["text"]
        # Should be plain text bullet, not a Slack link
        assert "\u2022 My Page" in text
        assert "<https://" not in text
        assert "[My Page]" not in text
