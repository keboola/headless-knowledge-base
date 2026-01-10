"""Tests for the chunking module."""

import pytest

from knowledge_base.chunking.markdown_chunker import MarkdownChunker, ChunkConfig


class TestMarkdownChunker:
    """Tests for MarkdownChunker."""

    def test_simple_paragraph(self):
        """Test chunking a simple paragraph."""
        chunker = MarkdownChunker(config=ChunkConfig(min_chunk_size=10))
        markdown = "This is a simple paragraph with some text content that is long enough to pass the minimum chunk size threshold for testing purposes."
        chunks = chunker.chunk(markdown, page_id="test-123", page_title="Test Page")

        assert len(chunks) == 1
        assert "simple paragraph" in chunks[0]["content"]
        assert chunks[0]["chunk_type"] == "text"
        assert chunks[0]["page_id"] == "test-123"

    def test_headers_tracked(self):
        """Test that header hierarchy is tracked."""
        chunker = MarkdownChunker(config=ChunkConfig(min_chunk_size=10))
        markdown = """# Main Title

## Section One

Content under section one with enough text to pass the minimum chunk size threshold for testing purposes.

## Section Two

Content under section two with enough text to pass the minimum chunk size threshold for testing purposes.
"""
        chunks = chunker.chunk(markdown, page_id="test-123")

        # Should have chunks with header context
        assert len(chunks) >= 2

    def test_code_block_preserved(self):
        """Test that code blocks are preserved as code type."""
        chunker = MarkdownChunker(config=ChunkConfig(min_chunk_size=10))
        # Code in its own section (after a header) gets detected as code type
        markdown = """## Code Example

```python
def hello():
    print("Hello, World!")
```
"""
        chunks = chunker.chunk(markdown, page_id="test-123")

        code_chunks = [c for c in chunks if c["chunk_type"] == "code"]
        assert len(code_chunks) >= 1
        assert "def hello" in code_chunks[0]["content"]

    def test_empty_markdown(self):
        """Test handling of empty markdown."""
        chunker = MarkdownChunker()
        chunks = chunker.chunk("", page_id="test-123")
        assert chunks == []

    def test_whitespace_only(self):
        """Test handling of whitespace-only markdown."""
        chunker = MarkdownChunker()
        chunks = chunker.chunk("   \n\n   ", page_id="test-123")
        assert chunks == []

    def test_chunk_id_unique(self):
        """Test that chunk IDs are unique."""
        chunker = MarkdownChunker(config=ChunkConfig(min_chunk_size=10))
        markdown = """First paragraph with enough content.

Second paragraph with enough content.

Third paragraph with enough content.
"""
        chunks = chunker.chunk(markdown, page_id="test-123")

        chunk_ids = [c["chunk_id"] for c in chunks]
        assert len(chunk_ids) == len(set(chunk_ids))

    def test_list_handling(self):
        """Test that lists are detected properly."""
        chunker = MarkdownChunker(config=ChunkConfig(min_chunk_size=10))
        markdown = """- First item with some content
- Second item with some content
- Third item with some content
- Fourth item with some content
"""
        chunks = chunker.chunk(markdown, page_id="test-123")

        list_chunks = [c for c in chunks if c["chunk_type"] == "list"]
        assert len(list_chunks) >= 1
        assert "First item" in list_chunks[0]["content"]
        assert "-" in list_chunks[0]["content"]

    def test_table_handling(self):
        """Test that tables are detected properly."""
        chunker = MarkdownChunker(config=ChunkConfig(min_chunk_size=10))
        markdown = """| Name | Age |
|------|-----|
| Alice | 30 |
| Bob | 25 |
"""
        chunks = chunker.chunk(markdown, page_id="test-123")

        table_chunks = [c for c in chunks if c["chunk_type"] == "table"]
        assert len(table_chunks) >= 1
        assert "Name" in table_chunks[0]["content"]
        assert "|" in table_chunks[0]["content"]

    def test_large_content_split(self):
        """Test that large content is split into smaller chunks."""
        config = ChunkConfig(max_chunk_size=200, min_chunk_size=10)
        chunker = MarkdownChunker(config=config)

        # Create content that exceeds max_chunk_size
        markdown = "\n\n".join([f"Paragraph {i} with enough content to make it meaningful." for i in range(20)])
        chunks = chunker.chunk(markdown, page_id="test-123")

        # Should have multiple chunks
        assert len(chunks) > 1
        # Each chunk should be under max size
        for chunk in chunks:
            assert chunk["char_count"] <= config.max_chunk_size

    def test_parent_headers_json(self):
        """Test that parent_headers is stored as JSON."""
        import json
        chunker = MarkdownChunker(config=ChunkConfig(min_chunk_size=10))
        markdown = """# Main Title

## Section One

Content under section one with enough text.
"""
        chunks = chunker.chunk(markdown, page_id="test-123")

        for chunk in chunks:
            # Should be valid JSON
            headers = json.loads(chunk["parent_headers"])
            assert isinstance(headers, list)

    def test_chunk_index_sequential(self):
        """Test that chunk indices are sequential."""
        chunker = MarkdownChunker(config=ChunkConfig(min_chunk_size=10))
        markdown = """## Section One

Content one with enough text.

## Section Two

Content two with enough text.

## Section Three

Content three with enough text.
"""
        chunks = chunker.chunk(markdown, page_id="test-123")

        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(indices)))


class TestChunkConfig:
    """Tests for ChunkConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ChunkConfig()
        assert config.min_chunk_size == 100
        assert config.max_chunk_size == 2000
        assert config.split_on_headers is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ChunkConfig(min_chunk_size=50, max_chunk_size=500)
        assert config.min_chunk_size == 50
        assert config.max_chunk_size == 500
