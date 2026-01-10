"""HTML to text chunker for Confluence content."""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

from knowledge_base.chunking.macro_handler import MacroHandler, clean_confluence_html
from knowledge_base.chunking.table_handler import TableHandler, is_table_element

logger = logging.getLogger(__name__)


@dataclass
class ChunkData:
    """Data for a single chunk."""

    content: str
    chunk_type: str = "text"  # text, code, table, list
    parent_headers: list[str] = field(default_factory=list)
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.content)


class HTMLChunker:
    """Converts HTML to clean text chunks suitable for embedding."""

    def __init__(
        self,
        max_chunk_size: int = 1000,
        overlap: int = 100,
        min_chunk_size: int = 100,
    ):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.min_chunk_size = min_chunk_size
        self.macro_handler = MacroHandler()
        self.table_handler = TableHandler()

    def chunk(self, html: str, page_id: str, page_title: str = "") -> list[dict]:
        """
        Convert HTML to chunks preserving structure.

        Args:
            html: Raw HTML content
            page_id: Confluence page ID
            page_title: Page title for context

        Returns:
            List of chunk dictionaries with chunk_id, content, type, etc.
        """
        if not html or not html.strip():
            return []

        # Clean Confluence-specific elements
        html = clean_confluence_html(html)

        # Parse HTML
        soup = BeautifulSoup(html, "lxml")

        # Process macros
        soup = self.macro_handler.process_html(soup)

        # Extract chunks
        raw_chunks = self._extract_chunks(soup)

        # Generate chunk IDs and format output
        chunks = []
        for i, chunk_data in enumerate(raw_chunks):
            if chunk_data.char_count < self.min_chunk_size and chunk_data.chunk_type == "text":
                continue  # Skip very small text chunks

            chunk_id = self._generate_chunk_id(page_id, i, chunk_data.content)
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "page_id": page_id,
                    "content": chunk_data.content,
                    "chunk_type": chunk_data.chunk_type,
                    "chunk_index": i,
                    "char_count": chunk_data.char_count,
                    "parent_headers": json.dumps(chunk_data.parent_headers),
                    "page_title": page_title,
                }
            )

        return chunks

    def _extract_chunks(self, soup: BeautifulSoup) -> list[ChunkData]:
        """Extract chunks from parsed HTML."""
        chunks: list[ChunkData] = []
        current_headers: list[str] = []
        current_text: list[str] = []

        def flush_text():
            """Flush accumulated text to chunks."""
            if current_text:
                text = "\n".join(current_text).strip()
                if text:
                    # Split if too large
                    for chunk_text in self._split_text(text):
                        chunks.append(
                            ChunkData(
                                content=chunk_text,
                                chunk_type="text",
                                parent_headers=current_headers.copy(),
                            )
                        )
                current_text.clear()

        # Process body content
        body = soup.find("body") or soup
        for element in body.children:
            if isinstance(element, NavigableString):
                text = str(element).strip()
                if text:
                    current_text.append(text)
                continue

            if not isinstance(element, Tag):
                continue

            # Headers
            if element.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                flush_text()
                header_text = element.get_text(strip=True)
                level = int(element.name[1])
                # Adjust header stack
                current_headers = current_headers[: level - 1]
                current_headers.append(header_text)
                continue

            # Code blocks
            if element.name == "pre" or (
                element.name == "div" and "code" in element.get("class", [])
            ):
                flush_text()
                code_text = element.get_text()
                # Preserve code formatting
                chunks.append(
                    ChunkData(
                        content=f"```\n{code_text}\n```",
                        chunk_type="code",
                        parent_headers=current_headers.copy(),
                    )
                )
                continue

            # Tables
            if is_table_element(element):
                flush_text()
                table_chunks = self.table_handler.process(element)
                for tc in table_chunks:
                    chunks.append(
                        ChunkData(
                            content=tc.content,
                            chunk_type="table",
                            parent_headers=current_headers.copy(),
                        )
                    )
                continue

            # Lists
            if element.name in ("ul", "ol"):
                flush_text()
                list_text = self._process_list(element)
                chunks.append(
                    ChunkData(
                        content=list_text,
                        chunk_type="list",
                        parent_headers=current_headers.copy(),
                    )
                )
                continue

            # Paragraphs and divs
            if element.name in ("p", "div", "span", "section", "article"):
                text = element.get_text(separator=" ", strip=True)
                if text:
                    current_text.append(text)
                continue

            # Other block elements
            text = element.get_text(separator=" ", strip=True)
            if text:
                current_text.append(text)

        # Flush remaining text
        flush_text()

        return chunks

    def _process_list(self, list_element: Tag) -> str:
        """Convert a list to formatted text."""
        lines = []
        items = list_element.find_all("li", recursive=False)
        is_ordered = list_element.name == "ol"

        for i, item in enumerate(items, 1):
            text = item.get_text(separator=" ", strip=True)
            if is_ordered:
                lines.append(f"{i}. {text}")
            else:
                lines.append(f"- {text}")

        return "\n".join(lines)

    def _split_text(self, text: str) -> list[str]:
        """Split text into chunks respecting max_chunk_size with overlap."""
        if len(text) <= self.max_chunk_size:
            return [text]

        chunks = []
        sentences = self._split_into_sentences(text)
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence_len = len(sentence)

            if current_length + sentence_len > self.max_chunk_size and current_chunk:
                # Save current chunk
                chunk_text = " ".join(current_chunk)
                chunks.append(chunk_text)

                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_chunk)
                current_chunk = [overlap_text] if overlap_text else []
                current_length = len(overlap_text) if overlap_text else 0

            current_chunk.append(sentence)
            current_length += sentence_len

        # Add final chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    def _split_into_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        # Simple sentence splitting
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]

    def _get_overlap_text(self, sentences: list[str]) -> str:
        """Get overlap text from the end of sentences."""
        if not sentences:
            return ""

        overlap_text = ""
        for sentence in reversed(sentences):
            if len(overlap_text) + len(sentence) > self.overlap:
                break
            overlap_text = sentence + " " + overlap_text

        return overlap_text.strip()

    def _generate_chunk_id(self, page_id: str, index: int, content: str) -> str:
        """Generate a unique chunk ID."""
        # Use hash of content for stability
        content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        return f"{page_id}-{index}-{content_hash}"
