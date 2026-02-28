"""Tests for Keboola downloader -- metadata parsing and row-to-ChunkData mapping."""

from collections import defaultdict
from unittest.mock import MagicMock, patch

import pytest

from knowledge_base.keboola.downloader import KeboolaDownloader
from knowledge_base.vectorstore.indexer import ChunkData


@pytest.fixture
def downloader() -> KeboolaDownloader:
    """Create a KeboolaDownloader with a mocked client."""
    mock_client = MagicMock()
    return KeboolaDownloader(client=mock_client, source_key="TEST_KEBOOLA")


# ---------------------------------------------------------------------------
# _parse_metadata tests
# ---------------------------------------------------------------------------


class TestParseMetadata:
    """Tests for _parse_metadata static method."""

    def test_standard_format(self) -> None:
        source, page_id = KeboolaDownloader._parse_metadata(
            "Confluence - Engineering Wiki-3218833620"
        )
        assert source == "Engineering Wiki"
        assert page_id == "3218833620"

    def test_space_with_hyphens(self) -> None:
        source, page_id = KeboolaDownloader._parse_metadata(
            "Confluence - My-Hyphenated-Space-12345"
        )
        assert source == "My-Hyphenated-Space"
        assert page_id == "12345"

    def test_no_separator(self) -> None:
        source, page_id = KeboolaDownloader._parse_metadata("JustAString")
        assert source == "JustAString"
        assert page_id == ""

    def test_empty_string(self) -> None:
        source, page_id = KeboolaDownloader._parse_metadata("")
        assert source == ""
        assert page_id == ""

    def test_source_only_no_page_id(self) -> None:
        source, page_id = KeboolaDownloader._parse_metadata(
            "Confluence - JustSourceName"
        )
        assert source == "JustSourceName"
        assert page_id == ""

    def test_multiple_dashes_in_source(self) -> None:
        source, page_id = KeboolaDownloader._parse_metadata(
            "Confluence - A - B - C-999"
        )
        assert source == "A - B - C"
        assert page_id == "999"

    def test_slack_format(self) -> None:
        """Potential Slack data format."""
        source, page_id = KeboolaDownloader._parse_metadata(
            "Slack - general-channel-42"
        )
        assert source == "general-channel"
        assert page_id == "42"


# ---------------------------------------------------------------------------
# _map_row_to_chunk tests
# ---------------------------------------------------------------------------


class TestMapRowToChunk:
    """Tests for _map_row_to_chunk."""

    def test_basic_mapping(self, downloader: KeboolaDownloader) -> None:
        row = {
            "text": "Some knowledge content here",
            "metadata": "Confluence - Engineering Wiki-3218833620",
        }
        counters: dict[str, int] = defaultdict(int)
        chunk = downloader._map_row_to_chunk(row, 0, "in.c-bucket.my-table", counters)

        assert chunk is not None
        assert chunk.content == "Some knowledge content here"
        assert chunk.page_id == "3218833620"
        assert chunk.page_title == "Engineering Wiki"
        assert chunk.chunk_id == "kbc_my-table_3218833620_0"
        assert chunk.space_key == "TEST_KEBOOLA"
        assert chunk.doc_type == "keboola_import"
        assert chunk.chunk_type == "text"

    def test_empty_text_returns_none(self, downloader: KeboolaDownloader) -> None:
        row = {"text": "", "metadata": "Confluence - Wiki-123"}
        counters: dict[str, int] = defaultdict(int)
        result = downloader._map_row_to_chunk(row, 0, "in.c-bucket.table", counters)
        assert result is None

    def test_whitespace_only_text_returns_none(self, downloader: KeboolaDownloader) -> None:
        row = {"text": "   \n\t  ", "metadata": "Confluence - Wiki-123"}
        counters: dict[str, int] = defaultdict(int)
        result = downloader._map_row_to_chunk(row, 0, "in.c-bucket.table", counters)
        assert result is None

    def test_missing_text_key_returns_none(self, downloader: KeboolaDownloader) -> None:
        row = {"metadata": "Confluence - Wiki-123"}
        counters: dict[str, int] = defaultdict(int)
        result = downloader._map_row_to_chunk(row, 0, "in.c-bucket.table", counters)
        assert result is None

    def test_missing_metadata_uses_fallback(self, downloader: KeboolaDownloader) -> None:
        row = {"text": "Content without metadata"}
        counters: dict[str, int] = defaultdict(int)
        chunk = downloader._map_row_to_chunk(row, 5, "in.c-bucket.table", counters)

        assert chunk is not None
        assert chunk.page_id == "kbc_row_5"
        assert "Keboola Import" in chunk.page_title

    def test_chunk_index_increments_per_page(self, downloader: KeboolaDownloader) -> None:
        """Multiple chunks from same page get incrementing chunk_index."""
        counters: dict[str, int] = defaultdict(int)

        row1 = {"text": "First chunk", "metadata": "Confluence - Wiki-100"}
        row2 = {"text": "Second chunk", "metadata": "Confluence - Wiki-100"}
        row3 = {"text": "Third chunk", "metadata": "Confluence - Wiki-200"}

        c1 = downloader._map_row_to_chunk(row1, 0, "in.c-bucket.t", counters)
        c2 = downloader._map_row_to_chunk(row2, 1, "in.c-bucket.t", counters)
        c3 = downloader._map_row_to_chunk(row3, 2, "in.c-bucket.t", counters)

        assert c1 is not None and c1.chunk_index == 0
        assert c2 is not None and c2.chunk_index == 1
        assert c3 is not None and c3.chunk_index == 0  # Different page_id resets

    def test_chunk_id_uniqueness(self, downloader: KeboolaDownloader) -> None:
        """All chunk IDs should be unique even for same page."""
        counters: dict[str, int] = defaultdict(int)

        rows = [
            {"text": f"Chunk {i}", "metadata": "Confluence - Wiki-100"}
            for i in range(5)
        ]
        chunk_ids = set()
        for i, row in enumerate(rows):
            chunk = downloader._map_row_to_chunk(row, i, "in.c-bucket.t", counters)
            assert chunk is not None
            chunk_ids.add(chunk.chunk_id)

        assert len(chunk_ids) == 5

    def test_chunk_id_prefix(self, downloader: KeboolaDownloader) -> None:
        """All chunk IDs start with kbc_ prefix."""
        counters: dict[str, int] = defaultdict(int)
        row = {"text": "Content", "metadata": "Confluence - Wiki-100"}
        chunk = downloader._map_row_to_chunk(row, 0, "in.c-bucket.table", counters)

        assert chunk is not None
        assert chunk.chunk_id.startswith("kbc_")

    def test_summary_truncated_for_long_content(self, downloader: KeboolaDownloader) -> None:
        """Summary is truncated to 200 chars for long content."""
        counters: dict[str, int] = defaultdict(int)
        long_text = "x" * 500
        row = {"text": long_text, "metadata": "Confluence - Wiki-100"}
        chunk = downloader._map_row_to_chunk(row, 0, "in.c-bucket.t", counters)

        assert chunk is not None
        assert len(chunk.summary) == 200


# ---------------------------------------------------------------------------
# fetch_chunks tests
# ---------------------------------------------------------------------------


class TestFetchChunks:
    """Tests for fetch_chunks."""

    def test_maps_all_rows(self, downloader: KeboolaDownloader) -> None:
        downloader.client.iter_table_rows.return_value = iter([
            {"text": "First", "metadata": "Confluence - Wiki-1"},
            {"text": "Second", "metadata": "Confluence - Wiki-2"},
            {"text": "Third", "metadata": "Confluence - Wiki-3"},
        ])

        with patch("knowledge_base.keboola.downloader.settings") as mock_settings:
            mock_settings.KEBOOLA_TABLE_ID = "in.c-bucket.table"
            mock_settings.KEBOOLA_SOURCE_KEY = "TEST"
            chunks = downloader.fetch_chunks("in.c-bucket.table")

        assert len(chunks) == 3
        assert all(isinstance(c, ChunkData) for c in chunks)

    def test_skips_empty_rows(self, downloader: KeboolaDownloader) -> None:
        downloader.client.iter_table_rows.return_value = iter([
            {"text": "Valid", "metadata": "Confluence - Wiki-1"},
            {"text": "", "metadata": "Confluence - Wiki-2"},
            {"text": "   ", "metadata": "Confluence - Wiki-3"},
            {"text": "Also valid", "metadata": "Confluence - Wiki-4"},
        ])

        chunks = downloader.fetch_chunks("in.c-bucket.table")

        assert len(chunks) == 2
        assert chunks[0].content == "Valid"
        assert chunks[1].content == "Also valid"

    def test_passes_changed_since(self, downloader: KeboolaDownloader) -> None:
        downloader.client.iter_table_rows.return_value = iter([])

        downloader.fetch_chunks("in.c-bucket.table", changed_since="2026-01-01T00:00:00")

        downloader.client.iter_table_rows.assert_called_once_with(
            "in.c-bucket.table",
            changed_since="2026-01-01T00:00:00",
        )

    def test_empty_table(self, downloader: KeboolaDownloader) -> None:
        downloader.client.iter_table_rows.return_value = iter([])
        chunks = downloader.fetch_chunks("in.c-bucket.table")
        assert chunks == []

    def test_custom_source_key(self) -> None:
        """Custom source_key propagates to chunk space_key."""
        mock_client = MagicMock()
        mock_client.iter_table_rows.return_value = iter([
            {"text": "Content", "metadata": "Confluence - Wiki-1"},
        ])

        dl = KeboolaDownloader(client=mock_client, source_key="CUSTOM_SOURCE")
        chunks = dl.fetch_chunks("in.c-bucket.table")

        assert len(chunks) == 1
        assert chunks[0].space_key == "CUSTOM_SOURCE"
