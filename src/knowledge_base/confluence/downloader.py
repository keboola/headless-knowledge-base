"""Confluence downloader with sync and rebase capabilities.

ARCHITECTURE NOTE (per docs/ARCHITECTURE.md):
- ChromaDB is the SOURCE OF TRUTH for knowledge data
- This downloader saves markdown files and indexes directly to ChromaDB
- RawPage in SQLite is kept only for sync tracking (not chunk storage)
"""

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_base.confluence.client import ConfluenceClient
from knowledge_base.confluence.markdown_converter import (
    delete_markdown_file,
    html_to_markdown,
    save_markdown_file,
)
from knowledge_base.confluence.models import GovernanceInfo, PageContent
from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker
# NOTE: GovernanceMetadata is DEPRECATED - governance data now in ChromaDB metadata
from knowledge_base.db.models import GovernanceMetadata, RawPage, calculate_staleness

logger = logging.getLogger(__name__)


class ConfluenceDownloader:
    """Downloads and syncs Confluence pages to the local database.

    After downloading, pages are automatically indexed to ChromaDB (source of truth).
    """

    def __init__(self, client: ConfluenceClient | None = None, index_to_chromadb: bool = True):
        """Initialize the downloader.

        Args:
            client: Confluence API client
            index_to_chromadb: If True, index chunks directly to ChromaDB after download
        """
        self.client = client or ConfluenceClient()
        self.index_to_chromadb = index_to_chromadb
        self._indexer = None

    def _get_indexer(self):
        """Lazy-load the vector indexer."""
        if self._indexer is None:
            from knowledge_base.vectorstore.indexer import VectorIndexer
            self._indexer = VectorIndexer()
        return self._indexer

    async def sync_space(
        self,
        space_key: str,
        force_update: bool = False,
        verbose: bool = False,
    ) -> dict:
        """
        Sync all pages from a Confluence space.

        Args:
            space_key: The Confluence space key
            force_update: If True, update all pages regardless of modification date
            verbose: If True, log detailed progress

        Returns:
            Statistics dict with counts of new, updated, skipped pages
        """
        stats = {"new": 0, "updated": 0, "skipped": 0, "errors": 0}

        async with async_session_maker() as session:
            async for page in self.client.get_all_pages(space_key):
                try:
                    # Check if page exists
                    existing = await self._get_existing_page(session, page.id)

                    if existing and not force_update:
                        # Check if page was updated
                        if existing.updated_at >= page.updated_at:
                            stats["skipped"] += 1
                            if verbose:
                                logger.debug(f"Skipping unchanged: {page.title}")
                            continue

                    # Fetch full content
                    content = await self.client.get_page_content(page.id, space_key)

                    # Get markdown content for indexing
                    markdown_content = html_to_markdown(content.html_content)

                    if existing:
                        await self._update_page(session, existing, content, markdown_content)
                        stats["updated"] += 1
                        if verbose:
                            logger.info(f"Updated: {content.title}")
                    else:
                        await self._create_page(session, content, markdown_content)
                        stats["new"] += 1
                        if verbose:
                            logger.info(f"Downloaded: {content.title}")

                    # Index to ChromaDB (source of truth)
                    if self.index_to_chromadb:
                        try:
                            governance_info = GovernanceInfo.from_labels(content.labels)
                            await self._index_page_to_chromadb(
                                content, markdown_content, governance_info
                            )
                            if verbose:
                                logger.debug(f"Indexed to ChromaDB: {content.title}")
                        except Exception as idx_err:
                            logger.warning(f"ChromaDB indexing failed for {content.id}: {idx_err}")

                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Error processing page {page.id}: {e}")

            await session.commit()

        logger.info(
            f"Space {space_key} sync complete: "
            f"{stats['new']} new, {stats['updated']} updated, "
            f"{stats['skipped']} skipped, {stats['errors']} errors"
        )
        return stats

    async def _get_existing_page(
        self, session: AsyncSession, page_id: str
    ) -> RawPage | None:
        """Get existing page by page_id."""
        result = await session.execute(
            select(RawPage).where(RawPage.page_id == page_id)
        )
        return result.scalar_one_or_none()

    def _map_status(self, confluence_status: str) -> str:
        """Map Confluence status to our internal status."""
        # Confluence uses 'current' for active pages
        status_map = {
            "current": "active",
            "draft": "draft",
            "trashed": "deleted",
        }
        return status_map.get(confluence_status, "active")

    async def _create_page(
        self, session: AsyncSession, content: PageContent, markdown_content: str
    ) -> None:
        """Create a new page record and save markdown file."""
        is_stale, stale_reason = calculate_staleness(content.updated_at)

        # Save markdown to file with random name
        file_path = save_markdown_file(markdown_content)

        page = RawPage(
            page_id=content.id,
            space_key=content.space_key,
            title=content.title,
            file_path=file_path,
            author=content.author,
            author_name=content.author_name,
            url=content.url,
            parent_id=content.parent_id,
            created_at=content.created_at,
            updated_at=content.updated_at,
            downloaded_at=datetime.utcnow(),
            version_number=content.version_number,
            permissions=json.dumps(
                [
                    {"type": p.type, "name": p.name, "operation": p.operation}
                    for p in content.permissions
                ]
            ),
            labels=json.dumps(content.labels),
            attachments=json.dumps(
                [
                    {
                        "id": a.id,
                        "title": a.title,
                        "media_type": a.media_type,
                        "file_size": a.file_size,
                        "download_url": a.download_url,
                    }
                    for a in content.attachments
                ]
            ),
            status=self._map_status(content.status),
            is_potentially_stale=is_stale,
            staleness_reason=stale_reason,
        )
        session.add(page)

        # Extract and store governance metadata
        governance_info = GovernanceInfo.from_labels(content.labels)
        governance = GovernanceMetadata(
            page_id=content.id,
            owner=governance_info.owner,
            reviewed_by=governance_info.reviewed_by,
            reviewed_at=governance_info.reviewed_at,
            classification=governance_info.classification,
            doc_type=governance_info.doc_type,
        )
        session.add(governance)

    async def _update_page(
        self, session: AsyncSession, existing: RawPage, content: PageContent, markdown_content: str
    ) -> None:
        """Update an existing page record and markdown file."""
        is_stale, stale_reason = calculate_staleness(content.updated_at)

        # Overwrite existing markdown file
        from pathlib import Path
        Path(existing.file_path).write_text(markdown_content, encoding="utf-8")

        existing.title = content.title
        existing.author = content.author
        existing.author_name = content.author_name
        existing.url = content.url
        existing.parent_id = content.parent_id
        existing.updated_at = content.updated_at
        existing.downloaded_at = datetime.utcnow()
        existing.version_number = content.version_number
        existing.permissions = json.dumps(
            [
                {"type": p.type, "name": p.name, "operation": p.operation}
                for p in content.permissions
            ]
        )
        existing.labels = json.dumps(content.labels)
        existing.attachments = json.dumps(
            [
                {
                    "id": a.id,
                    "title": a.title,
                    "media_type": a.media_type,
                    "file_size": a.file_size,
                    "download_url": a.download_url,
                }
                for a in content.attachments
            ]
        )
        existing.status = self._map_status(content.status)
        existing.is_potentially_stale = is_stale
        existing.staleness_reason = stale_reason

        # Update governance metadata
        governance_info = GovernanceInfo.from_labels(content.labels)
        if existing.governance:
            existing.governance.owner = governance_info.owner
            existing.governance.reviewed_by = governance_info.reviewed_by
            existing.governance.reviewed_at = governance_info.reviewed_at
            existing.governance.classification = governance_info.classification
            existing.governance.doc_type = governance_info.doc_type
        else:
            governance = GovernanceMetadata(
                page_id=content.id,
                owner=governance_info.owner,
                reviewed_by=governance_info.reviewed_by,
                reviewed_at=governance_info.reviewed_at,
                classification=governance_info.classification,
                doc_type=governance_info.doc_type,
            )
            session.add(governance)

    async def _index_page_to_chromadb(
        self,
        content: PageContent,
        markdown_content: str,
        governance_info: GovernanceInfo,
    ) -> int:
        """Index a page's chunks directly to ChromaDB (source of truth).

        Args:
            content: Page content from Confluence
            markdown_content: Markdown text to chunk and index
            governance_info: Extracted governance metadata

        Returns:
            Number of chunks indexed
        """
        from knowledge_base.chunking.markdown_chunker import MarkdownChunker
        from knowledge_base.vectorstore.indexer import ChunkData

        # Chunk the markdown content
        chunker = MarkdownChunker()
        chunks = chunker.chunk(markdown_content, content.id, content.title)

        if not chunks:
            return 0

        # Build ChunkData objects for direct ChromaDB indexing
        chunk_data_list = []
        for i, chunk in enumerate(chunks):
            chunk_id = f"{content.id}_{i}"
            chunk_content = chunk.get("content", chunk) if isinstance(chunk, dict) else chunk
            chunk_type = chunk.get("chunk_type", "text") if isinstance(chunk, dict) else "text"
            parent_headers = chunk.get("parent_headers", []) if isinstance(chunk, dict) else []

            import json
            chunk_data = ChunkData(
                chunk_id=chunk_id,
                content=chunk_content,
                page_id=content.id,
                page_title=content.title,
                chunk_index=i,
                space_key=content.space_key,
                url=content.url,
                author=content.author,
                created_at=content.created_at.isoformat() if content.created_at else "",
                updated_at=content.updated_at.isoformat() if content.updated_at else "",
                chunk_type=chunk_type,
                parent_headers=json.dumps(parent_headers),
                quality_score=100.0,  # Default score for new content
                access_count=0,
                feedback_count=0,
                owner=governance_info.owner or "",
                reviewed_by=governance_info.reviewed_by or "",
                reviewed_at=governance_info.reviewed_at.isoformat() if governance_info.reviewed_at else "",
                classification=governance_info.classification or "internal",
                doc_type=governance_info.doc_type or "",
            )
            chunk_data_list.append(chunk_data)

        # Index to ChromaDB
        indexer = self._get_indexer()
        await indexer.index_chunks_direct(chunk_data_list)

        return len(chunk_data_list)

    async def sync_all_spaces(
        self,
        space_keys: list[str] | None = None,
        force_update: bool = False,
        verbose: bool = False,
    ) -> dict:
        """
        Sync all configured spaces.

        Args:
            space_keys: List of space keys to sync (defaults to configured spaces)
            force_update: If True, update all pages
            verbose: If True, log detailed progress

        Returns:
            Aggregated statistics
        """
        spaces = space_keys or settings.confluence_space_list
        if not spaces:
            raise ValueError("No spaces configured. Set CONFLUENCE_SPACE_KEYS.")

        total_stats = {"new": 0, "updated": 0, "skipped": 0, "errors": 0}

        for space_key in spaces:
            logger.info(f"Syncing space: {space_key}")
            stats = await self.sync_space(
                space_key, force_update=force_update, verbose=verbose
            )
            for key in total_stats:
                total_stats[key] += stats[key]

        logger.info(
            f"Total sync complete: "
            f"{total_stats['new']} new, {total_stats['updated']} updated, "
            f"{total_stats['skipped']} skipped, {total_stats['errors']} errors"
        )
        return total_stats

    async def mark_deleted_pages(self, space_key: str) -> int:
        """
        Mark pages as deleted if they no longer exist in Confluence.

        Returns:
            Number of pages marked as deleted
        """
        async with async_session_maker() as session:
            # Get all page IDs from Confluence
            confluence_ids = set()
            async for page in self.client.get_all_pages(space_key):
                confluence_ids.add(page.id)

            # Get all page IDs from database for this space
            result = await session.execute(
                select(RawPage.page_id).where(
                    RawPage.space_key == space_key, RawPage.status == "active"
                )
            )
            db_ids = {row[0] for row in result.fetchall()}

            # Find deleted pages
            deleted_ids = db_ids - confluence_ids
            if deleted_ids:
                for page_id in deleted_ids:
                    result = await session.execute(
                        select(RawPage).where(RawPage.page_id == page_id)
                    )
                    page = result.scalar_one_or_none()
                    if page:
                        page.status = "deleted"
                        logger.info(f"Marked as deleted: {page.title}")

                await session.commit()

            return len(deleted_ids)


async def rebase_from_confluence(space_keys: list[str] | None = None) -> dict:
    """
    Manual rebase: re-download all pages from Confluence.

    Preserves feedback/quality scores (linked by page_id).

    Args:
        space_keys: List of spaces to rebase (defaults to all configured)

    Returns:
        Sync statistics
    """
    downloader = ConfluenceDownloader()
    return await downloader.sync_all_spaces(
        space_keys=space_keys, force_update=True, verbose=True
    )
