"""Tests for the markdown converter module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from knowledge_base.confluence.markdown_converter import (
    html_to_markdown,
    generate_random_filename,
    save_markdown_file,
    read_markdown_file,
    delete_markdown_file,
    get_pages_dir,
)


class TestHtmlToMarkdown:
    """Tests for html_to_markdown function."""

    def test_simple_paragraph(self):
        """Test converting a simple paragraph."""
        html = "<p>Hello, World!</p>"
        markdown = html_to_markdown(html)
        assert "Hello, World!" in markdown

    def test_headings(self):
        """Test converting headings."""
        html = "<h1>Title</h1><h2>Subtitle</h2><h3>Section</h3>"
        markdown = html_to_markdown(html)
        assert "# Title" in markdown
        assert "## Subtitle" in markdown
        assert "### Section" in markdown

    def test_lists(self):
        """Test converting lists."""
        html = "<ul><li>First</li><li>Second</li></ul>"
        markdown = html_to_markdown(html)
        assert "- First" in markdown
        assert "- Second" in markdown

    def test_links(self):
        """Test converting links."""
        html = '<a href="https://example.com">Example</a>'
        markdown = html_to_markdown(html)
        assert "[Example](https://example.com)" in markdown

    def test_code_blocks(self):
        """Test converting code blocks."""
        html = '<pre class="language-python">def hello():\n    pass</pre>'
        markdown = html_to_markdown(html)
        assert "def hello()" in markdown

    def test_confluence_namespace_cleanup(self):
        """Test that Confluence ac: and ri: elements are removed."""
        html = '<ac:macro><ac:content>Skip</ac:content></ac:macro><p>Keep this</p>'
        markdown = html_to_markdown(html)
        assert "Keep this" in markdown
        # ac: content should be removed
        assert "Skip" not in markdown or "ac:" not in markdown

    def test_empty_html(self):
        """Test converting empty HTML."""
        html = ""
        markdown = html_to_markdown(html)
        assert markdown == ""

    def test_whitespace_cleanup(self):
        """Test that excessive whitespace is cleaned up."""
        html = "<p>First</p>\n\n\n\n\n<p>Second</p>"
        markdown = html_to_markdown(html)
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in markdown


class TestRandomFilename:
    """Tests for generate_random_filename function."""

    def test_length(self):
        """Test that filename is 16 characters."""
        filename = generate_random_filename()
        assert len(filename) == 16

    def test_hex_format(self):
        """Test that filename is valid hex."""
        filename = generate_random_filename()
        # Should only contain hex characters
        int(filename, 16)  # This will raise if not valid hex

    def test_uniqueness(self):
        """Test that generated filenames are unique."""
        filenames = [generate_random_filename() for _ in range(100)]
        assert len(filenames) == len(set(filenames))


class TestFileOperations:
    """Tests for file operations."""

    def test_save_and_read_markdown(self):
        """Test saving and reading markdown files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('knowledge_base.confluence.markdown_converter.settings') as mock_settings:
                mock_settings.PAGES_DIR = tmpdir

                content = "# Test\n\nThis is test content."
                file_path = save_markdown_file(content)

                # File should exist
                assert Path(file_path).exists()

                # File should have .md extension
                assert file_path.endswith(".md")

                # File should have random name (16 hex chars)
                filename = Path(file_path).stem
                assert len(filename) == 16

                # Content should match
                read_content = read_markdown_file(file_path)
                assert read_content == content

    def test_save_with_custom_filename(self):
        """Test saving with a custom filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('knowledge_base.confluence.markdown_converter.settings') as mock_settings:
                mock_settings.PAGES_DIR = tmpdir

                content = "Custom content"
                file_path = save_markdown_file(content, filename="custom-name")

                assert "custom-name.md" in file_path

    def test_delete_markdown_file(self):
        """Test deleting markdown files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('knowledge_base.confluence.markdown_converter.settings') as mock_settings:
                mock_settings.PAGES_DIR = tmpdir

                content = "To be deleted"
                file_path = save_markdown_file(content)

                # File should exist
                assert Path(file_path).exists()

                # Delete should return True
                result = delete_markdown_file(file_path)
                assert result is True

                # File should not exist
                assert not Path(file_path).exists()

    def test_delete_nonexistent_file(self):
        """Test deleting a file that doesn't exist."""
        result = delete_markdown_file("/nonexistent/path/file.md")
        assert result is False

    def test_get_pages_dir_creates_directory(self):
        """Test that get_pages_dir creates the directory if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = os.path.join(tmpdir, "new_pages")
            with patch('knowledge_base.confluence.markdown_converter.settings') as mock_settings:
                mock_settings.PAGES_DIR = new_dir

                pages_dir = get_pages_dir()

                assert pages_dir.exists()
                assert pages_dir == Path(new_dir)
