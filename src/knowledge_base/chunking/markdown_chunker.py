"""Markdown chunker for splitting markdown files into semantic chunks."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ChunkConfig:
    """Configuration for chunking behavior."""

    min_chunk_size: int = 100  # Minimum characters per chunk
    max_chunk_size: int = 2000  # Maximum characters per chunk
    split_on_headers: bool = True


class MarkdownChunker:
    """Splits markdown content into semantic chunks."""

    def __init__(self, config: ChunkConfig | None = None):
        self.config = config or ChunkConfig()

    def chunk(
        self,
        markdown: str,
        page_id: str,
        page_title: str = "",
    ) -> list[dict]:
        """
        Split markdown content into chunks.

        Args:
            markdown: The markdown content to chunk
            page_id: The page ID for reference
            page_title: The page title for context

        Returns:
            List of chunk dictionaries
        """
        if not markdown or not markdown.strip():
            return []

        chunks = []
        current_headers = []

        # Split content by headers
        sections = self._split_by_headers(markdown)

        chunk_index = 0
        for section in sections:
            header = section.get("header")
            level = section.get("level", 0)
            content = section.get("content", "").strip()

            # Update header stack
            if header:
                # Maintain header hierarchy
                current_headers = [h for h in current_headers if h["level"] < level]
                current_headers.append({"level": level, "text": header})

            if not content:
                continue

            # Determine chunk type
            chunk_type = self._detect_chunk_type(content)

            # Split large content
            content_chunks = self._split_content(content, chunk_type)

            for chunk_content in content_chunks:
                if len(chunk_content) < self.config.min_chunk_size:
                    continue

                chunk_id = self._generate_chunk_id(page_id, chunk_index, chunk_content)

                chunks.append({
                    "chunk_id": chunk_id,
                    "page_id": page_id,
                    "content": chunk_content,
                    "chunk_type": chunk_type,
                    "chunk_index": chunk_index,
                    "char_count": len(chunk_content),
                    "parent_headers": json.dumps([h["text"] for h in current_headers]),
                    "page_title": page_title,
                })
                chunk_index += 1

        return chunks

    def _split_by_headers(self, markdown: str) -> list[dict]:
        """Split markdown by headers into sections."""
        # Match markdown headers (# Header, ## Header, etc.)
        header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

        sections = []
        last_end = 0

        for match in header_pattern.finditer(markdown):
            # Content before this header
            if match.start() > last_end:
                content = markdown[last_end:match.start()].strip()
                if content:
                    sections.append({
                        "header": None,
                        "level": 0,
                        "content": content,
                    })

            last_end = match.end()

            # Find content after header until next header or end
            next_match = header_pattern.search(markdown, match.end())
            end_pos = next_match.start() if next_match else len(markdown)
            content = markdown[match.end():end_pos].strip()

            sections.append({
                "header": match.group(2).strip(),
                "level": len(match.group(1)),
                "content": content,
            })
            last_end = end_pos

        # Content after last header
        if last_end < len(markdown):
            content = markdown[last_end:].strip()
            if content:
                sections.append({
                    "header": None,
                    "level": 0,
                    "content": content,
                })

        # If no headers found, return whole content as one section
        if not sections:
            sections.append({
                "header": None,
                "level": 0,
                "content": markdown.strip(),
            })

        return sections

    def _detect_chunk_type(self, content: str) -> str:
        """Detect the type of content in a chunk."""
        # Code block
        if content.startswith("```") or re.match(r"^\s{4,}", content, re.MULTILINE):
            return "code"

        # Table (markdown table)
        if re.search(r"\|.*\|.*\|", content) and re.search(r"\|[-:]+\|", content):
            return "table"

        # List (bullet or numbered)
        lines = content.strip().split("\n")
        list_lines = sum(1 for line in lines if re.match(r"^\s*[-*+]|\d+\.", line.strip()))
        if list_lines > len(lines) * 0.5:
            return "list"

        return "text"

    def _split_content(self, content: str, chunk_type: str) -> list[str]:
        """Split content into smaller chunks if needed."""
        if len(content) <= self.config.max_chunk_size:
            return [content]

        chunks = []

        if chunk_type == "list":
            # Split lists by items
            chunks = self._split_list(content)
        elif chunk_type == "table":
            # Keep tables intact if possible, otherwise split by rows
            chunks = self._split_table(content)
        else:
            # Split by paragraphs
            chunks = self._split_paragraphs(content)

        return chunks

    def _split_paragraphs(self, content: str) -> list[str]:
        """Split text content by paragraphs."""
        paragraphs = re.split(r"\n\n+", content)
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 <= self.config.max_chunk_size:
                current_chunk = f"{current_chunk}\n\n{para}".strip()
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _split_list(self, content: str) -> list[str]:
        """Split list content by items."""
        lines = content.split("\n")
        chunks = []
        current_chunk = ""

        for line in lines:
            if len(current_chunk) + len(line) + 1 <= self.config.max_chunk_size:
                current_chunk = f"{current_chunk}\n{line}".strip()
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _split_table(self, content: str) -> list[str]:
        """Split table content by rows."""
        lines = content.split("\n")
        if len(lines) <= 3:  # Header, separator, one row
            return [content]

        chunks = []
        header_lines = lines[:2]  # Header + separator
        header = "\n".join(header_lines)

        current_chunk = header
        for line in lines[2:]:
            if len(current_chunk) + len(line) + 1 <= self.config.max_chunk_size:
                current_chunk = f"{current_chunk}\n{line}"
            else:
                chunks.append(current_chunk)
                current_chunk = f"{header}\n{line}"

        if current_chunk and current_chunk != header:
            chunks.append(current_chunk)

        return chunks if chunks else [content]

    def _generate_chunk_id(self, page_id: str, index: int, content: str) -> str:
        """Generate a unique chunk ID."""
        content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        return f"{page_id}-{index}-{content_hash}"


def chunk_markdown_file(file_path: str, page_id: str, page_title: str = "") -> list[dict]:
    """
    Convenience function to chunk a markdown file.

    Args:
        file_path: Path to the markdown file
        page_id: The page ID for reference
        page_title: The page title for context

    Returns:
        List of chunk dictionaries
    """
    content = Path(file_path).read_text(encoding="utf-8")
    chunker = MarkdownChunker()
    return chunker.chunk(content, page_id, page_title)
