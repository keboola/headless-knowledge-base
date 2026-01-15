"""Handler for /ingest-doc slash command - ingest external documents.

Uses ChromaDB as the source of truth for indexed chunks.
See docs/adr/0005-chromadb-source-of-truth.md for architecture details.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from slack_sdk import WebClient

from knowledge_base.db.database import async_session_maker
# RawPage kept for sync tracking only
from knowledge_base.db.models import RawPage
from knowledge_base.chunking.markdown_chunker import MarkdownChunker, ChunkConfig
from knowledge_base.vectorstore.indexer import VectorIndexer, ChunkData

logger = logging.getLogger(__name__)

# Supported content types
SUPPORTED_TYPES = {
    "webpage": ["text/html", "application/xhtml+xml"],
    "pdf": ["application/pdf"],
    "text": ["text/plain", "text/markdown"],
}

# URL patterns for special handling
GOOGLE_DOCS_PATTERN = re.compile(r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)")
NOTION_PATTERN = re.compile(r"notion\.so/.*?([a-f0-9]{32})")


class DocumentIngester:
    """Ingests external documents into the knowledge base."""

    def __init__(self):
        self.chunker = MarkdownChunker(ChunkConfig(min_chunk_size=100, max_chunk_size=2000))
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "KeboolaKnowledgeBot/1.0 (Document Ingestion)"
            }
        )

    async def ingest_url(
        self,
        url: str,
        created_by: str,
        channel_id: str,
    ) -> dict:
        """Ingest a document from a URL.

        Args:
            url: URL to ingest
            created_by: Slack user ID of creator
            channel_id: Channel where command was issued

        Returns:
            Result dict with status, chunks_created, title, etc.
        """
        try:
            # Detect document type
            doc_type = self._detect_doc_type(url)

            if doc_type == "google_doc":
                return await self._ingest_google_doc(url, created_by, channel_id)
            elif doc_type == "notion":
                return await self._ingest_notion(url, created_by, channel_id)
            else:
                return await self._ingest_webpage(url, created_by, channel_id)

        except Exception as e:
            logger.error(f"Failed to ingest {url}: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "url": url,
            }

    def _detect_doc_type(self, url: str) -> str:
        """Detect the type of document from URL."""
        if GOOGLE_DOCS_PATTERN.search(url):
            return "google_doc"
        if NOTION_PATTERN.search(url):
            return "notion"
        if url.lower().endswith(".pdf"):
            return "pdf"
        return "webpage"

    async def _ingest_webpage(
        self,
        url: str,
        created_by: str,
        channel_id: str,
    ) -> dict:
        """Ingest a webpage by fetching and parsing HTML."""
        # Fetch the page
        response = await self.http_client.get(url)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()

        # Handle PDF
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return await self._ingest_pdf(url, response.content, created_by, channel_id)

        # Parse HTML
        soup = BeautifulSoup(response.text, "lxml")

        # Extract title
        title = self._extract_title(soup, url)

        # Extract main content
        content = self._extract_main_content(soup)

        if not content or len(content.strip()) < 50:
            return {
                "status": "error",
                "error": "Could not extract meaningful content from page",
                "url": url,
            }

        # Convert to markdown
        markdown_content = md(content, heading_style="ATX", bullets="-")

        # Create and index
        return await self._create_and_index(
            url=url,
            title=title,
            content=markdown_content,
            created_by=created_by,
            source_type="webpage",
        )

    async def _ingest_pdf(
        self,
        url: str,
        pdf_bytes: bytes,
        created_by: str,
        channel_id: str,
    ) -> dict:
        """Ingest a PDF document."""
        try:
            # Try to import pypdf
            from pypdf import PdfReader
            import io

            reader = PdfReader(io.BytesIO(pdf_bytes))

            # Extract title from metadata or URL
            title = reader.metadata.title if reader.metadata and reader.metadata.title else None
            if not title:
                # Extract from URL
                parsed = urlparse(url)
                title = parsed.path.split("/")[-1].replace(".pdf", "").replace("-", " ").replace("_", " ")

            # Extract text from all pages
            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

            if not text_parts:
                return {
                    "status": "error",
                    "error": "Could not extract text from PDF (may be scanned/image-based)",
                    "url": url,
                }

            content = "\n\n".join(text_parts)

            return await self._create_and_index(
                url=url,
                title=title,
                content=content,
                created_by=created_by,
                source_type="pdf",
            )

        except ImportError:
            return {
                "status": "error",
                "error": "PDF support not installed. Add 'pypdf' to dependencies.",
                "url": url,
            }

    async def _ingest_google_doc(
        self,
        url: str,
        created_by: str,
        channel_id: str,
    ) -> dict:
        """Ingest a Google Doc (public or with link sharing)."""
        # Extract document ID
        match = GOOGLE_DOCS_PATTERN.search(url)
        if not match:
            return {
                "status": "error",
                "error": "Could not parse Google Doc URL",
                "url": url,
            }

        doc_id = match.group(1)

        # Try to export as HTML (works for public/link-shared docs)
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=html"

        try:
            response = await self.http_client.get(export_url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            title = self._extract_title(soup, url) or f"Google Doc {doc_id[:8]}"

            # Get body content
            body = soup.find("body")
            if body:
                content = md(str(body), heading_style="ATX", bullets="-")
            else:
                content = md(response.text, heading_style="ATX", bullets="-")

            return await self._create_and_index(
                url=url,
                title=title,
                content=content,
                created_by=created_by,
                source_type="google_doc",
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                return {
                    "status": "error",
                    "error": "Google Doc is not publicly accessible. Enable link sharing.",
                    "url": url,
                }
            raise

    async def _ingest_notion(
        self,
        url: str,
        created_by: str,
        channel_id: str,
    ) -> dict:
        """Ingest a Notion page (requires public page or API setup)."""
        # For now, try to fetch the public page
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            title = self._extract_title(soup, url) or "Notion Page"

            # Notion pages have complex structure, try to get main content
            content_div = soup.find("div", {"class": re.compile("notion-page-content")})
            if content_div:
                content = md(str(content_div), heading_style="ATX", bullets="-")
            else:
                # Fallback to full body
                body = soup.find("body")
                content = md(str(body), heading_style="ATX", bullets="-") if body else ""

            if not content or len(content.strip()) < 50:
                return {
                    "status": "error",
                    "error": "Could not extract content from Notion. Make page public or use Notion API.",
                    "url": url,
                }

            return await self._create_and_index(
                url=url,
                title=title,
                content=content,
                created_by=created_by,
                source_type="notion",
            )

        except httpx.HTTPStatusError as e:
            return {
                "status": "error",
                "error": f"Could not access Notion page: {e.response.status_code}",
                "url": url,
            }

    def _extract_title(self, soup: BeautifulSoup, url: str) -> str:
        """Extract title from HTML."""
        # Try various title sources
        if soup.title and soup.title.string:
            return soup.title.string.strip()

        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"]

        # Fallback to URL
        parsed = urlparse(url)
        return parsed.path.split("/")[-1] or parsed.netloc

    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """Extract main content from HTML, removing navigation, ads, etc."""
        # Remove unwanted elements
        for tag in soup.find_all(["nav", "header", "footer", "aside", "script", "style", "noscript"]):
            tag.decompose()

        # Remove elements with common ad/nav classes
        for class_pattern in ["nav", "menu", "sidebar", "footer", "header", "ad", "advertisement", "cookie"]:
            for elem in soup.find_all(class_=re.compile(class_pattern, re.I)):
                elem.decompose()

        # Try to find main content container
        main_content = None

        # Priority order of content containers
        for selector in ["main", "article", "[role='main']", ".content", ".post", ".article", "#content"]:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if main_content:
            return str(main_content)

        # Fallback to body
        body = soup.find("body")
        return str(body) if body else str(soup)

    async def _create_and_index(
        self,
        url: str,
        title: str,
        content: str,
        created_by: str,
        source_type: str,
    ) -> dict:
        """Create RawPage record and index content directly to ChromaDB.

        ChromaDB is the source of truth for chunk data. RawPage is kept
        in SQLite only for sync tracking purposes.
        """
        page_id = f"ingest_{uuid.uuid4().hex[:16]}"
        now = datetime.utcnow()
        now_iso = now.isoformat()

        async with async_session_maker() as session:
            # Create RawPage record for sync tracking only
            page = RawPage(
                page_id=page_id,
                space_key="INGESTED",
                title=title,
                file_path="ingested",
                author=created_by,
                author_name=f"Ingested by {created_by}",
                url=url,
                created_at=now,
                updated_at=now,
                version_number=1,
                status="active",
                is_potentially_stale=False,
            )
            session.add(page)
            await session.commit()

        # Chunk the content
        raw_chunks = self.chunker.chunk(content, page_id, title)

        if not raw_chunks:
            # Single chunk for small content
            raw_chunks = [{
                "content": content,
                "chunk_type": "text",
                "parent_headers": [],
            }]

        # Build ChunkData objects for direct ChromaDB indexing
        chunks_to_index: list[ChunkData] = []
        for i, raw_chunk in enumerate(raw_chunks):
            chunk_id = f"{page_id}_{i}"

            # Handle both dict and string chunk formats
            if isinstance(raw_chunk, dict):
                chunk_content = raw_chunk.get("content", "")
                chunk_type = raw_chunk.get("chunk_type", "text")
                parent_headers = raw_chunk.get("parent_headers", [])
            else:
                chunk_content = raw_chunk
                chunk_type = "text"
                parent_headers = []

            # Create ChunkData for direct ChromaDB indexing
            chunk_data = ChunkData(
                chunk_id=chunk_id,
                content=chunk_content,
                page_id=page_id,
                page_title=title,
                chunk_index=i,
                space_key="INGESTED",
                url=url,
                author=f"Ingested by {created_by}",
                created_at=now_iso,
                updated_at=now_iso,
                chunk_type=chunk_type,
                parent_headers=json.dumps(parent_headers) if isinstance(parent_headers, list) else parent_headers,
                quality_score=100.0,  # Default score
                access_count=0,
                feedback_count=0,
                doc_type=source_type,
                topics="[]",
                summary=chunk_content[:200] if chunk_content else "",
            )
            chunks_to_index.append(chunk_data)

        # Index directly to ChromaDB (source of truth)
        try:
            indexer = VectorIndexer()
            await indexer.index_chunks_direct(chunks_to_index)
            logger.info(f"Ingested and indexed {len(chunks_to_index)} chunks from {url}")

        except Exception as e:
            logger.error(f"Failed to index ingested content: {e}")
            raise  # Don't silently fail - ChromaDB is source of truth

        return {
            "status": "success",
            "url": url,
            "title": title,
            "source_type": source_type,
            "chunks_created": len(chunks_to_index),
            "page_id": page_id,
        }

    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()


# Global ingester instance
_ingester: DocumentIngester | None = None


def get_ingester() -> DocumentIngester:
    """Get or create the document ingester."""
    global _ingester
    if _ingester is None:
        _ingester = DocumentIngester()
    return _ingester


async def handle_ingest_doc(ack: Any, command: dict, client: WebClient) -> None:
    """Handle the /ingest-doc slash command.

    Usage: /ingest-doc <url>
    Supported: Web pages, PDFs, Google Docs (public), Notion (public)

    NOTE: This uses background task processing to avoid Slack's 3-second timeout
    in Cloud Run deployments. Document ingestion can take 5-30 seconds depending
    on document size (fetching, parsing, chunking, embedding generation).
    """
    # CRITICAL: Acknowledge immediately to avoid timeout
    await ack()

    text = command.get("text", "").strip()
    user_id = command.get("user_id")
    channel_id = command.get("channel_id")

    if not text:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=(
                "*Usage:* `/ingest-doc <url>`\n\n"
                "*Supported sources:*\n"
                "• Web pages (HTML)\n"
                "• PDF documents\n"
                "• Google Docs (must have link sharing enabled)\n"
                "• Notion pages (must be public)\n\n"
                "*Example:*\n"
                "`/ingest-doc https://docs.company.com/guide.pdf`"
            ),
        )
        return

    # Validate URL
    try:
        parsed = urlparse(text)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Invalid URL")
    except Exception:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Invalid URL: `{text}`\n\nPlease provide a valid URL starting with http:// or https://",
        )
        return

    # Send immediate response - don't wait for ingestion
    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=f"⏳ Ingesting document from `{text}`...\n_This may take a moment (up to 30 seconds for large documents)._",
    )

    # Process the ingestion in a background task to avoid blocking
    async def process_ingestion():
        """Background task to handle the actual ingestion work."""
        try:
            ingester = get_ingester()
            result = await ingester.ingest_url(text, user_id, channel_id)

            if result["status"] == "success":
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=(
                        f"✅ *Document ingested successfully!*\n\n"
                        f"*Title:* {result['title']}\n"
                        f"*Source:* {result['source_type']}\n"
                        f"*Chunks created:* {result['chunks_created']}\n\n"
                        f"_The content is now searchable in the knowledge base._"
                    ),
                )
            else:
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"❌ *Failed to ingest document*\n\nError: {result.get('error', 'Unknown error')}",
                )

        except Exception as e:
            logger.error(f"Error in /ingest-doc: {e}", exc_info=True)
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"❌ *Error ingesting document:* {str(e)}",
            )

    # Start the background task and return immediately
    asyncio.create_task(process_ingestion())


def register_ingest_handler(app):
    """Register the /ingest-doc command handler."""
    app.command("/ingest-doc")(handle_ingest_doc)
