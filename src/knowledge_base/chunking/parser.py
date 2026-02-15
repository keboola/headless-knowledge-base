"""Parser service for processing raw pages into chunks.

DEPRECATED: This module uses SQLite Chunk model which is deprecated.
Use ConfluenceDownloader._index_page_to_graphiti() for new code.

The preferred approach is:
1. Use MarkdownChunker to chunk content
2. Create ChunkData objects
3. Index directly to Graphiti via GraphitiIndexer

See docs/ARCHITECTURE.md for architecture details.
"""

import logging
import warnings
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_base.chunking.markdown_chunker import MarkdownChunker
from knowledge_base.db.database import async_session_maker
# NOTE: Chunk is DEPRECATED - use vectorstore.indexer.ChunkData instead
# RawPage is kept for Confluence sync tracking
from knowledge_base.db.models import Chunk, RawPage

logger = logging.getLogger(__name__)

# Emit deprecation warning when module is imported
warnings.warn(
    "knowledge_base.chunking.parser is deprecated. "
    "Use ConfluenceDownloader for direct ChromaDB indexing.",
    DeprecationWarning,
    stacklevel=2,
)


class PageParser:
    """Parses markdown files into chunks and stores them."""

    def __init__(self, chunker: MarkdownChunker | None = None):
        self.chunker = chunker or MarkdownChunker()

    async def parse_all_pages(
        self,
        space_key: str | None = None,
        force: bool = False,
        verbose: bool = False,
    ) -> dict:
        """
        Parse all raw pages into chunks.

        Args:
            space_key: Optional space key to filter pages
            force: If True, re-parse all pages (delete existing chunks)
            verbose: If True, log detailed progress

        Returns:
            Statistics dictionary
        """
        stats = {"pages": 0, "chunks": 0, "errors": 0}

        async with async_session_maker() as session:
            # Build query
            query = select(RawPage).where(RawPage.status == "active")
            if space_key:
                query = query.where(RawPage.space_key == space_key)

            result = await session.execute(query)
            pages = result.scalars().all()

            for page in pages:
                try:
                    if force:
                        # Delete existing chunks for this page
                        await session.execute(
                            delete(Chunk).where(Chunk.page_id == page.page_id)
                        )

                    chunk_count = await self._parse_page(session, page, verbose)
                    stats["pages"] += 1
                    stats["chunks"] += chunk_count

                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Error parsing page {page.page_id}: {e}")

            await session.commit()

        logger.info(
            f"Parsing complete: {stats['pages']} pages, "
            f"{stats['chunks']} chunks, {stats['errors']} errors"
        )
        return stats

    async def parse_page(self, page_id: str, force: bool = False) -> int:
        """
        Parse a single page into chunks.

        Args:
            page_id: The page ID to parse
            force: If True, delete existing chunks first

        Returns:
            Number of chunks created
        """
        async with async_session_maker() as session:
            # Get the page
            result = await session.execute(
                select(RawPage).where(RawPage.page_id == page_id)
            )
            page = result.scalar_one_or_none()

            if not page:
                raise ValueError(f"Page not found: {page_id}")

            if force:
                await session.execute(
                    delete(Chunk).where(Chunk.page_id == page_id)
                )

            chunk_count = await self._parse_page(session, page, verbose=True)
            await session.commit()

            return chunk_count

    async def _parse_page(
        self, session: AsyncSession, page: RawPage, verbose: bool = False
    ) -> int:
        """Parse a single page and store chunks."""
        # Check if already parsed (has chunks)
        existing = await session.execute(
            select(Chunk).where(Chunk.page_id == page.page_id).limit(1)
        )
        if existing.scalar_one_or_none():
            if verbose:
                logger.debug(f"Skipping already parsed: {page.title}")
            return 0

        # Read markdown content from file
        try:
            markdown_content = Path(page.file_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.error(f"Markdown file not found: {page.file_path}")
            return 0

        # Parse markdown into chunks
        chunks_data = self.chunker.chunk(
            markdown=markdown_content,
            page_id=page.page_id,
            page_title=page.title,
        )

        if verbose:
            logger.info(f"Parsed {len(chunks_data)} chunks from: {page.title}")

        # Store chunks
        for chunk_data in chunks_data:
            chunk = Chunk(
                chunk_id=chunk_data["chunk_id"],
                page_id=chunk_data["page_id"],
                content=chunk_data["content"],
                chunk_type=chunk_data["chunk_type"],
                chunk_index=chunk_data["chunk_index"],
                char_count=chunk_data["char_count"],
                parent_headers=chunk_data["parent_headers"],
                page_title=chunk_data["page_title"],
            )
            session.add(chunk)

        return len(chunks_data)

    async def get_stats(self, space_key: str | None = None) -> dict:
        """Get parsing statistics."""
        from sqlalchemy import func

        async with async_session_maker() as session:
            # Total chunks
            query = select(func.count(Chunk.id))
            if space_key:
                query = query.join(RawPage).where(RawPage.space_key == space_key)
            total_chunks = (await session.execute(query)).scalar()

            # Chunks by type
            type_query = (
                select(Chunk.chunk_type, func.count(Chunk.id))
                .group_by(Chunk.chunk_type)
            )
            if space_key:
                type_query = type_query.join(RawPage).where(RawPage.space_key == space_key)
            type_counts = dict((await session.execute(type_query)).fetchall())

            # Pages with chunks
            pages_query = select(func.count(func.distinct(Chunk.page_id)))
            if space_key:
                pages_query = pages_query.join(RawPage).where(RawPage.space_key == space_key)
            pages_with_chunks = (await session.execute(pages_query)).scalar()

            # Average chunk size
            avg_query = select(func.avg(Chunk.char_count))
            if space_key:
                avg_query = avg_query.join(RawPage).where(RawPage.space_key == space_key)
            avg_size = (await session.execute(avg_query)).scalar()

            return {
                "total_chunks": total_chunks or 0,
                "chunks_by_type": type_counts,
                "pages_with_chunks": pages_with_chunks or 0,
                "average_chunk_size": int(avg_size) if avg_size else 0,
            }
