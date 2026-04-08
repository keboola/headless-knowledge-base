"""CLI commands for the knowledge base."""

import asyncio
import logging
import re
import sys

import click

from knowledge_base.config import settings


class SecretRedactingFilter(logging.Filter):
    """Filter to redact sensitive information from logs."""

    # Patterns for common secrets
    SECRET_PATTERNS = [
        (re.compile(r"(api[_-]?key[\s:=]+)[\w-]{20,}", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(token[\s:=]+)[\w-]{20,}", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(password[\s:=]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(secret[\s:=]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(bearer\s+)[\w-]+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(authorization[\s:]+bearer\s+)[\w-]+", re.IGNORECASE), r"\1[REDACTED]"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact secrets from log messages."""
        if isinstance(record.msg, str):
            for pattern, replacement in self.SECRET_PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        return True


# Configure logging with secret redaction
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger().addFilter(SecretRedactingFilter())
logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def cli(verbose: bool) -> None:
    """Knowledge Base CLI."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


@cli.command()
@click.option(
    "--spaces",
    "-s",
    help="Comma-separated list of space keys (defaults to configured spaces)",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
@click.option("--resume", "-r", is_flag=True, help="Resume from last position (skip unchanged)")
def download(spaces: str | None, verbose: bool, resume: bool) -> None:
    """Download pages from Confluence spaces."""
    asyncio.run(_download(spaces, verbose, resume))


async def _download(spaces: str | None, verbose: bool, resume: bool) -> None:
    """Async implementation of download command."""
    from knowledge_base.confluence.downloader import ConfluenceDownloader
    from knowledge_base.db.database import init_db

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Parse space keys
    space_list: list[str] | None = None
    if spaces:
        space_list = [s.strip() for s in spaces.split(",") if s.strip()]

    if not space_list and not settings.confluence_space_list:
        click.echo("Error: No spaces specified. Use --spaces or set CONFLUENCE_SPACE_KEYS.", err=True)
        sys.exit(1)

    # Download pages
    downloader = ConfluenceDownloader()
    try:
        stats = await downloader.sync_all_spaces(
            space_keys=space_list,
            force_update=not resume,
            verbose=verbose,
        )
        click.echo(f"\nDownload complete!")
        click.echo(f"  New pages: {stats['new']}")
        click.echo(f"  Updated pages: {stats['updated']}")
        click.echo(f"  Skipped (unchanged): {stats['skipped']}")
        click.echo(f"  Errors: {stats['errors']}")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        sys.exit(1)


@cli.command()
@click.option(
    "--spaces",
    "-s",
    help="Comma-separated list of space keys (defaults to configured spaces)",
)
@click.option("--full", is_flag=True, help="Full sync (re-download everything)")
@click.option("--rebase", is_flag=True, help="Rebase from Confluence (force update all)")
def sync(spaces: str | None, full: bool, rebase: bool) -> None:
    """Sync pages from Confluence (incremental or full)."""
    asyncio.run(_sync(spaces, full, rebase))


async def _sync(spaces: str | None, full: bool, rebase: bool) -> None:
    """Async implementation of sync command."""
    from knowledge_base.confluence.downloader import ConfluenceDownloader, rebase_from_confluence
    from knowledge_base.db.database import init_db

    # Initialize database
    await init_db()

    # Parse space keys
    space_list: list[str] | None = None
    if spaces:
        space_list = [s.strip() for s in spaces.split(",") if s.strip()]

    if rebase:
        click.echo("Rebasing from Confluence (force update)...")
        stats = await rebase_from_confluence(space_list)
    else:
        downloader = ConfluenceDownloader()
        stats = await downloader.sync_all_spaces(
            space_keys=space_list,
            force_update=full,
            verbose=True,
        )

    click.echo(f"\nSync complete!")
    click.echo(f"  New pages: {stats['new']}")
    click.echo(f"  Updated pages: {stats['updated']}")
    click.echo(f"  Skipped: {stats['skipped']}")
    click.echo(f"  Errors: {stats['errors']}")


@cli.command()
def init_database() -> None:
    """Initialize the database schema."""
    asyncio.run(_init_database())


async def _init_database() -> None:
    """Async implementation of init-database command."""
    from knowledge_base.db.database import init_db

    await init_db()
    click.echo("Database initialized successfully!")


@cli.command()
def check_connection() -> None:
    """Check connection to Confluence."""
    asyncio.run(_check_connection())


async def _check_connection() -> None:
    """Async implementation of check-connection command."""
    from knowledge_base.confluence.client import ConfluenceClient

    client = ConfluenceClient()
    try:
        spaces = await client.get_spaces()
        click.echo(f"Connected to Confluence successfully!")
        click.echo(f"Found {len(spaces)} spaces:")
        for space in spaces[:10]:  # Show first 10
            click.echo(f"  - {space.get('key')}: {space.get('name')}")
        if len(spaces) > 10:
            click.echo(f"  ... and {len(spaces) - 10} more")
    except Exception as e:
        click.echo(f"Connection failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--space", "-s", help="Parse only pages from this space")
@click.option("--force", "-f", is_flag=True, help="Re-parse all pages (delete existing chunks)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
def parse(space: str | None, force: bool, verbose: bool) -> None:
    """Parse downloaded pages into chunks."""
    asyncio.run(_parse(space, force, verbose))


async def _parse(space: str | None, force: bool, verbose: bool) -> None:
    """Async implementation of parse command."""
    from knowledge_base.chunking.parser import PageParser
    from knowledge_base.db.database import init_db

    await init_db()

    parser = PageParser()
    stats = await parser.parse_all_pages(
        space_key=space,
        force=force,
        verbose=verbose,
    )

    click.echo(f"\nParsing complete!")
    click.echo(f"  Pages processed: {stats['pages']}")
    click.echo(f"  Chunks created: {stats['chunks']}")
    click.echo(f"  Errors: {stats['errors']}")

    # Show chunk statistics
    chunk_stats = await parser.get_stats(space)
    click.echo(f"\nChunk Statistics:")
    click.echo(f"  Total chunks: {chunk_stats['total_chunks']}")
    click.echo(f"  Pages with chunks: {chunk_stats['pages_with_chunks']}")
    click.echo(f"  Average chunk size: {chunk_stats['average_chunk_size']} chars")
    if chunk_stats['chunks_by_type']:
        click.echo(f"  By type:")
        for chunk_type, count in chunk_stats['chunks_by_type'].items():
            click.echo(f"    {chunk_type}: {count}")


@cli.command()
@click.option("--space", "-s", help="Generate metadata only for pages from this space")
@click.option("--regenerate", "-r", is_flag=True, help="Regenerate metadata for all chunks")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
@click.option("--batch-size", "-b", type=int, default=10, help="Batch size for LLM calls")
def metadata(space: str | None, regenerate: bool, verbose: bool, batch_size: int) -> None:
    """Generate metadata for document chunks using LLM."""
    asyncio.run(_metadata(space, regenerate, verbose, batch_size))


async def _metadata(space: str | None, regenerate: bool, verbose: bool, batch_size: int) -> None:
    """Async implementation of metadata command.

    NOTE: This command uses deprecated SQLite models (Chunk, ChunkMetadata).
    Future versions should store metadata directly in ChromaDB.
    See docs/adr/0005-chromadb-source-of-truth.md for migration plan.
    """
    import warnings
    from datetime import datetime

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from knowledge_base.db.database import async_session_maker, init_db
    from knowledge_base.db.models import Chunk, ChunkMetadata, RawPage
    from knowledge_base.metadata import MetadataExtractor, metadata_to_db_dict
    from knowledge_base.rag.factory import get_llm
    from knowledge_base.rag.exceptions import LLMProviderNotConfiguredError

    warnings.warn(
        "The 'metadata' command uses deprecated SQLite models. "
        "Future versions will store metadata directly in ChromaDB.",
        DeprecationWarning,
    )

    await init_db()

    # Check LLM availability
    try:
        llm = await get_llm()
    except LLMProviderNotConfiguredError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not await llm.check_health():
        click.echo(
            f"Error: LLM provider '{llm.provider_name}' is not healthy.", err=True
        )
        sys.exit(1)

    click.echo(f"Using LLM provider: {llm.provider_name} (model: {llm.model})")

    extractor = MetadataExtractor(llm)

    async with async_session_maker() as session:
        # Build query for chunks that need metadata
        query = (
            select(Chunk)
            .join(RawPage, Chunk.page_id == RawPage.page_id)
            .where(RawPage.status == "active")
        )

        if space:
            query = query.where(RawPage.space_key == space)

        if not regenerate:
            # Only get chunks without metadata
            query = query.outerjoin(ChunkMetadata).where(ChunkMetadata.id == None)

        query = query.options(selectinload(Chunk.page))

        result = await session.execute(query)
        chunks = result.scalars().all()

        if not chunks:
            click.echo("No chunks need metadata generation.")
            return

        click.echo(f"Found {len(chunks)} chunks to process")

        # Process in batches
        total_processed = 0
        total_errors = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            # Prepare batch items
            items = [(chunk.chunk_id, chunk.content, chunk.page_title) for chunk in batch]

            # Extract metadata for batch
            results = await extractor.extract_batch(items, concurrency=batch_size)

            # Store results
            for chunk in batch:
                if chunk.chunk_id in results:
                    metadata_obj = results[chunk.chunk_id]
                    db_data = metadata_to_db_dict(metadata_obj)

                    # Check if metadata exists (for regenerate mode)
                    existing = await session.execute(
                        select(ChunkMetadata).where(ChunkMetadata.chunk_id == chunk.chunk_id)
                    )
                    existing_meta = existing.scalar_one_or_none()

                    if existing_meta:
                        # Update existing
                        for key, value in db_data.items():
                            setattr(existing_meta, key, value)
                        existing_meta.generated_at = datetime.utcnow()
                    else:
                        # Create new
                        new_meta = ChunkMetadata(
                            chunk_id=chunk.chunk_id,
                            generated_at=datetime.utcnow(),
                            **db_data,
                        )
                        session.add(new_meta)

                    total_processed += 1
                else:
                    total_errors += 1

            await session.commit()

            if verbose:
                click.echo(f"  Processed batch {i // batch_size + 1}: {len(batch)} chunks")
            else:
                # Progress indicator
                progress = (i + len(batch)) / len(chunks) * 100
                click.echo(f"\rProgress: {progress:.1f}% ({i + len(batch)}/{len(chunks)})", nl=False)

        if not verbose:
            click.echo()  # New line after progress

        click.echo(f"\nMetadata generation complete!")
        click.echo(f"  Processed: {total_processed}")
        click.echo(f"  Errors: {total_errors}")


@cli.command()
@click.option("--space", "-s", help="Index only pages from this space")
@click.option("--reindex", "-r", is_flag=True, help="Delete and rebuild the index")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
def index(space: str | None, reindex: bool, verbose: bool) -> None:
    """Index chunks into Graphiti for search."""
    asyncio.run(_index(space, reindex, verbose))


async def _index(space: str | None, reindex: bool, verbose: bool) -> None:
    """Async implementation of index command.

    NOTE: Graphiti is now the source of truth. Indexing happens automatically
    during Confluence sync. This command indexes from markdown files for
    pages that may not have been indexed yet.
    """
    from pathlib import Path
    from sqlalchemy import select

    from knowledge_base.db.database import async_session_maker, init_db
    from knowledge_base.db.models import RawPage
    from knowledge_base.graph.graphiti_indexer import GraphitiIndexer
    from knowledge_base.vectorstore.indexer import ChunkData
    from knowledge_base.chunking.markdown_chunker import MarkdownChunker

    await init_db()

    click.echo("NOTE: Graphiti is now the source of truth. Indexing to graph database.")

    indexer = GraphitiIndexer()
    chunker = MarkdownChunker()

    if reindex:
        click.echo("Reindexing: Note - existing data will be overwritten...")

    async with async_session_maker() as session:
        try:
            # Get pages to index from RawPage table
            query = select(RawPage).where(RawPage.status == "active")
            if space:
                query = query.where(RawPage.space_key == space)

            result = await session.execute(query)
            pages = result.scalars().all()

            click.echo(f"Found {len(pages)} pages to index")
            total_chunks = 0

            for i, page in enumerate(pages):
                # Read markdown file
                md_path = Path(page.file_path)
                if not md_path.exists():
                    if verbose:
                        click.echo(f"  Skipping {page.title}: file not found")
                    continue

                markdown_content = md_path.read_text(encoding="utf-8")
                chunks = chunker.chunk(markdown_content, page.page_id, page.title)

                if not chunks:
                    continue

                # Build ChunkData for direct indexing
                import json
                chunk_data_list = []
                for idx, chunk in enumerate(chunks):
                    chunk_id = f"{page.page_id}_{idx}"
                    chunk_content = chunk.get("content", chunk) if isinstance(chunk, dict) else chunk
                    chunk_type = chunk.get("chunk_type", "text") if isinstance(chunk, dict) else "text"
                    parent_headers = chunk.get("parent_headers", []) if isinstance(chunk, dict) else []

                    chunk_data = ChunkData(
                        chunk_id=chunk_id,
                        content=chunk_content,
                        page_id=page.page_id,
                        page_title=page.title,
                        chunk_index=idx,
                        space_key=page.space_key,
                        url=page.url,
                        author=page.author,
                        created_at=page.created_at.isoformat() if page.created_at else "",
                        updated_at=page.updated_at.isoformat() if page.updated_at else "",
                        chunk_type=chunk_type,
                        parent_headers=json.dumps(parent_headers),
                    )
                    chunk_data_list.append(chunk_data)

                await indexer.index_chunks_direct(chunk_data_list)
                total_chunks += len(chunk_data_list)

                if verbose:
                    click.echo(f"  Indexed {page.title}: {len(chunk_data_list)} chunks")
                else:
                    progress = (i + 1) / len(pages) * 100
                    click.echo(f"\rProgress: {progress:.1f}% ({i + 1}/{len(pages)} pages)", nl=False)

            if not verbose and pages:
                click.echo()  # New line after progress

            click.echo(f"\nIndexing complete!")
            click.echo(f"  Chunks indexed: {total_chunks}")

            # Show stats
            stats_count = await indexer.get_chunk_count()
            click.echo(f"  Total in index: {stats_count}")

        except Exception as e:
            logger.error(f"Indexing failed: {e}")
            click.echo(f"\nError: {e}", err=True)
            sys.exit(1)


@cli.command()
def stats() -> None:
    """Show database statistics."""
    asyncio.run(_stats())


async def _stats() -> None:
    """Show database and Graphiti statistics."""
    from sqlalchemy import func, select

    from knowledge_base.db.database import async_session_maker, init_db
    from knowledge_base.db.models import RawPage
    from knowledge_base.graph.graphiti_builder import get_graphiti_builder

    await init_db()

    async with async_session_maker() as session:
        # Total pages
        total = await session.execute(select(func.count(RawPage.id)))
        total_count = total.scalar()

        # By status
        active = await session.execute(
            select(func.count(RawPage.id)).where(RawPage.status == "active")
        )
        active_count = active.scalar()

        deleted = await session.execute(
            select(func.count(RawPage.id)).where(RawPage.status == "deleted")
        )
        deleted_count = deleted.scalar()

        # Stale pages
        stale = await session.execute(
            select(func.count(RawPage.id)).where(RawPage.is_potentially_stale == True)
        )
        stale_count = stale.scalar()

        # By space
        spaces = await session.execute(
            select(RawPage.space_key, func.count(RawPage.id))
            .group_by(RawPage.space_key)
        )

        click.echo("Database Statistics:")
        click.echo(f"  Total pages: {total_count}")
        click.echo(f"  Active: {active_count}")
        click.echo(f"  Deleted: {deleted_count}")
        click.echo(f"  Potentially stale: {stale_count}")
        click.echo("\nPages by space:")
        for space_key, count in spaces.fetchall():
            click.echo(f"  {space_key}: {count}")

    # Get chunk statistics from Graphiti (source of truth)
    builder = get_graphiti_builder()
    try:
        graphiti_stats = await builder.get_stats()
        click.echo(f"\nChunk Statistics (Graphiti):")
        click.echo(f"  Backend: {graphiti_stats.get('backend', 'unknown')}")
        click.echo(f"  Enabled: {graphiti_stats.get('enabled', False)}")
        if 'episode_count' in graphiti_stats:
            click.echo(f"  Total episodes: {graphiti_stats['episode_count']}")
    except Exception as e:
        click.echo(f"\nChunk Statistics: Unable to connect to Graphiti ({e})")


# =============================================================================
# LIFECYCLE MANAGEMENT COMMANDS
# =============================================================================


@cli.group()
def lifecycle() -> None:
    """Knowledge lifecycle management commands."""
    pass


@lifecycle.command(name="stats")
def lifecycle_stats() -> None:
    """Show lifecycle statistics (quality, feedback, archival, conflicts)."""
    asyncio.run(_lifecycle_stats())


async def _lifecycle_stats() -> None:
    """Async implementation of lifecycle stats command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.lifecycle import (
        get_archival_stats,
        get_conflict_stats,
        get_feedback_stats,
    )

    await init_db()

    click.echo("Knowledge Lifecycle Statistics")
    click.echo("=" * 50)

    # Feedback stats
    feedback = await get_feedback_stats()
    click.echo("\nFeedback:")
    click.echo(f"  Total: {feedback['total']}")
    click.echo(f"  Unreviewed: {feedback['unreviewed']}")
    if feedback['by_type']:
        click.echo("  By type:")
        for ftype, count in feedback['by_type'].items():
            click.echo(f"    {ftype}: {count}")

    # Archival stats
    archival = await get_archival_stats()
    click.echo("\nQuality Status:")
    if archival['by_status']:
        for status, count in archival['by_status'].items():
            click.echo(f"  {status}: {count}")
    click.echo(f"  Cold storage: {archival['cold_storage_count']}")

    # Conflict stats
    conflicts = await get_conflict_stats()
    click.echo("\nConflicts:")
    click.echo(f"  Total: {conflicts['total']}")
    if conflicts['by_status']:
        click.echo("  By status:")
        for status, count in conflicts['by_status'].items():
            click.echo(f"    {status}: {count}")
    if conflicts['by_type']:
        click.echo("  By type:")
        for ctype, count in conflicts['by_type'].items():
            click.echo(f"    {ctype}: {count}")


@lifecycle.command(name="init-quality")
def init_quality() -> None:
    """Initialize quality records for all chunks."""
    asyncio.run(_init_quality())


async def _init_quality() -> None:
    """Async implementation of init-quality command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.lifecycle import initialize_all_chunk_quality

    await init_db()

    click.echo("Initializing quality records for all chunks...")
    stats = await initialize_all_chunk_quality()

    click.echo(f"\nQuality initialization complete!")
    click.echo(f"  Initialized: {stats['initialized']}")
    click.echo(f"  Skipped (already exists): {stats['skipped']}")


@lifecycle.command(name="run-archival")
def run_archival() -> None:
    """Run the archival pipeline (deprecate, cold archive, hard archive)."""
    asyncio.run(_run_archival())


async def _run_archival() -> None:
    """Async implementation of run-archival command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.lifecycle import run_archival_pipeline

    await init_db()

    click.echo("Running archival pipeline...")
    stats = await run_archival_pipeline()

    click.echo(f"\nArchival pipeline complete!")
    click.echo(f"  Deprecated: {stats['deprecated']}")
    click.echo(f"  Cold archived: {stats['cold_archived']}")
    click.echo(f"  Hard archived: {stats['hard_archived']}")
    click.echo(f"  Restored: {stats['restored']}")


@lifecycle.command(name="recalculate-quality")
def recalculate_quality() -> None:
    """Recalculate quality scores based on decay and feedback."""
    asyncio.run(_recalculate_quality())


async def _recalculate_quality() -> None:
    """Async implementation of recalculate-quality command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.lifecycle import recalculate_quality_scores, update_rolling_access_counts

    await init_db()

    click.echo("Updating rolling access counts...")
    access_stats = await update_rolling_access_counts()
    click.echo(f"  Updated: {access_stats['updated']} records")

    click.echo("Recalculating quality scores...")
    quality_stats = await recalculate_quality_scores()

    click.echo(f"\nQuality recalculation complete!")
    click.echo(f"  Recalculated: {quality_stats['recalculated']}")
    click.echo(f"  Decayed: {quality_stats['decayed']}")


@lifecycle.command(name="cleanup-logs")
@click.option("--days", "-d", type=int, default=90, help="Delete logs older than N days")
def cleanup_logs(days: int) -> None:
    """Clean up old access logs."""
    asyncio.run(_cleanup_logs(days))


async def _cleanup_logs(days: int) -> None:
    """Async implementation of cleanup-logs command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.lifecycle import cleanup_old_access_logs

    await init_db()

    click.echo(f"Cleaning up access logs older than {days} days...")
    stats = await cleanup_old_access_logs(days)

    click.echo(f"\nCleanup complete!")
    click.echo(f"  Deleted: {stats['deleted']} log entries")


@lifecycle.command(name="conflicts")
@click.option("--limit", "-l", type=int, default=20, help="Maximum conflicts to show")
def show_conflicts(limit: int) -> None:
    """Show open conflicts awaiting resolution."""
    asyncio.run(_show_conflicts(limit))


async def _show_conflicts(limit: int) -> None:
    """Async implementation of conflicts command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.lifecycle import get_open_conflicts

    await init_db()

    conflicts = await get_open_conflicts(limit)

    if not conflicts:
        click.echo("No open conflicts.")
        return

    click.echo(f"Open Conflicts ({len(conflicts)} found):")
    click.echo("-" * 70)

    for c in conflicts:
        click.echo(f"\nID: {c.id}")
        click.echo(f"  Type: {c.conflict_type}")
        click.echo(f"  Chunks: {c.chunk_a_id[:20]}... <-> {c.chunk_b_id[:20]}...")
        click.echo(f"  Detected by: {c.detected_by}")
        if c.similarity_score:
            click.echo(f"  Similarity: {c.similarity_score:.2f}")
        if c.confidence_score:
            click.echo(f"  Confidence: {c.confidence_score:.2f}")
        click.echo(f"  Description: {c.description[:80]}...")


@lifecycle.command(name="feedback")
@click.option("--unreviewed", "-u", is_flag=True, help="Show only unreviewed feedback")
@click.option("--high-impact", "-h", is_flag=True, help="Show high-impact feedback (outdated/incorrect)")
@click.option("--limit", "-l", type=int, default=20, help="Maximum feedback items to show")
def show_feedback(unreviewed: bool, high_impact: bool, limit: int) -> None:
    """Show user feedback on content chunks."""
    asyncio.run(_show_feedback(unreviewed, high_impact, limit))


async def _show_feedback(unreviewed: bool, high_impact: bool, limit: int) -> None:
    """Async implementation of feedback command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.lifecycle import get_high_impact_feedback, get_unreviewed_feedback

    await init_db()

    if high_impact:
        feedback_list = await get_high_impact_feedback(limit)
        title = "High-Impact Feedback"
    elif unreviewed:
        feedback_list = await get_unreviewed_feedback(limit)
        title = "Unreviewed Feedback"
    else:
        feedback_list = await get_unreviewed_feedback(limit)
        title = "Recent Feedback"

    if not feedback_list:
        click.echo(f"No {title.lower()} found.")
        return

    click.echo(f"{title} ({len(feedback_list)} items):")
    click.echo("-" * 70)

    for f in feedback_list:
        click.echo(f"\nID: {f.id}")
        click.echo(f"  Chunk: {f.chunk_id[:30]}...")
        click.echo(f"  Type: {f.feedback_type}")
        click.echo(f"  User: {f.slack_username}")
        click.echo(f"  Date: {f.created_at}")
        if f.comment:
            click.echo(f"  Comment: {f.comment[:60]}...")
        click.echo(f"  Reviewed: {'Yes' if f.reviewed else 'No'}")


@lifecycle.command(name="run-all")
def run_all_lifecycle() -> None:
    """Run all lifecycle maintenance tasks."""
    asyncio.run(_run_all_lifecycle())


async def _run_all_lifecycle() -> None:
    """Async implementation of run-all command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.lifecycle import (
        cleanup_old_access_logs,
        recalculate_quality_scores,
        run_archival_pipeline,
        update_rolling_access_counts,
    )

    await init_db()

    click.echo("Running all lifecycle maintenance tasks...")
    click.echo("=" * 50)

    # 1. Update access counts
    click.echo("\n1. Updating rolling access counts...")
    access_stats = await update_rolling_access_counts()
    click.echo(f"   Updated: {access_stats['updated']} records")

    # 2. Recalculate quality scores
    click.echo("\n2. Recalculating quality scores...")
    quality_stats = await recalculate_quality_scores()
    click.echo(f"   Recalculated: {quality_stats['recalculated']}")
    click.echo(f"   Decayed: {quality_stats['decayed']}")

    # 3. Run archival pipeline
    click.echo("\n3. Running archival pipeline...")
    archival_stats = await run_archival_pipeline()
    click.echo(f"   Deprecated: {archival_stats['deprecated']}")
    click.echo(f"   Cold archived: {archival_stats['cold_archived']}")
    click.echo(f"   Hard archived: {archival_stats['hard_archived']}")
    click.echo(f"   Restored: {archival_stats['restored']}")

    # 4. Cleanup old logs
    click.echo("\n4. Cleaning up old access logs...")
    cleanup_stats = await cleanup_old_access_logs(90)
    click.echo(f"   Deleted: {cleanup_stats['deleted']} log entries")

    click.echo("\n" + "=" * 50)
    click.echo("Lifecycle maintenance complete!")


@lifecycle.command(name="score-stats")
def score_stats() -> None:
    """Show quality score statistics (Phase 11)."""
    asyncio.run(_score_stats())


async def _score_stats() -> None:
    """Async implementation of score-stats command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.lifecycle import get_quality_stats

    await init_db()

    stats = await get_quality_stats()

    click.echo("Quality Score Statistics (Phase 11)")
    click.echo("=" * 50)
    click.echo(f"\nChunks tracked: {stats['total_tracked']}")
    click.echo(f"Average score: {stats['average_score']}")
    click.echo(f"Score range: {stats['min_score']} - {stats['max_score']}")
    click.echo(f"Feedback (last 7 days): {stats['feedback_last_7_days']}")

    if stats['by_status']:
        click.echo("\nBy status:")
        for status, count in stats['by_status'].items():
            click.echo(f"  {status}: {count}")


@lifecycle.command(name="show-score")
@click.argument("chunk_id")
def show_score(chunk_id: str) -> None:
    """Show quality score for a specific chunk."""
    asyncio.run(_show_score(chunk_id))


async def _show_score(chunk_id: str) -> None:
    """Async implementation of show-score command.

    Retrieves quality score from Graphiti (source of truth).
    """
    from knowledge_base.db.database import init_db
    from knowledge_base.graph.graphiti_builder import get_graphiti_builder
    from knowledge_base.lifecycle.feedback import get_feedback_for_chunk

    await init_db()

    # Get chunk info from Graphiti (source of truth)
    builder = get_graphiti_builder()
    episode = await builder.get_chunk_episode(chunk_id)

    if not episode:
        click.echo(f"Chunk not found in Graphiti: {chunk_id}", err=True)
        return

    content = episode.get("content", "")
    metadata = episode.get("metadata", {})

    page_title = metadata.get("page_title", "Unknown")
    quality_score = metadata.get("quality_score", 100.0)
    access_count = metadata.get("access_count", 0)
    feedback_count = metadata.get("feedback_count", 0)
    updated_at = metadata.get("updated_at", "")

    click.echo(f"Quality Score for Chunk: {chunk_id[:40]}...")
    click.echo("=" * 50)
    click.echo(f"\nPage: {page_title}")
    click.echo(f"Content preview: {content[:100]}...")

    click.echo(f"\nQuality Score (Graphiti): {quality_score:.1f}/100")
    click.echo(f"  Access count: {access_count}")
    click.echo(f"  Feedback count: {feedback_count}")
    click.echo(f"  Last updated: {updated_at}")

    # Get feedback details from analytics DB
    feedbacks = await get_feedback_for_chunk(chunk_id)
    if feedbacks:
        helpful = sum(1 for f in feedbacks if f.feedback_type == "helpful")
        negative = len(feedbacks) - helpful
        click.echo(f"\nFeedback History (from analytics DB):")
        click.echo(f"  Total feedbacks: {len(feedbacks)}")
        click.echo(f"  Helpful: {helpful}")
        click.echo(f"  Negative: {negative}")


# =============================================================================
# SLACK BOT COMMANDS
# =============================================================================


@cli.command()
@click.option("--port", "-p", type=int, default=3000, help="Port to run on")
@click.option("--socket-mode", "-s", is_flag=True, help="Use Socket Mode (requires SLACK_APP_TOKEN)")
def slack_bot(port: int, socket_mode: bool) -> None:
    """Run the Slack bot server."""
    from knowledge_base.config import settings

    if not settings.SLACK_BOT_TOKEN:
        click.echo("Error: SLACK_BOT_TOKEN not set in environment", err=True)
        sys.exit(1)

    if not settings.SLACK_SIGNING_SECRET:
        click.echo("Error: SLACK_SIGNING_SECRET not set in environment", err=True)
        sys.exit(1)

    if socket_mode and not settings.SLACK_APP_TOKEN:
        click.echo("Error: SLACK_APP_TOKEN required for socket mode", err=True)
        sys.exit(1)

    from knowledge_base.slack import run_bot

    click.echo(f"Starting Slack bot...")
    click.echo(f"  Mode: {'Socket Mode' if socket_mode else f'HTTP on port {port}'}")

    if not socket_mode:
        click.echo(f"  Set Request URL in Slack to: https://YOUR_NGROK_URL/slack/events")

    run_bot(port=port, use_socket_mode=socket_mode)


@cli.command()
@click.option(
    "--spaces",
    "-s",
    help="Comma-separated list of space keys (defaults to configured spaces)",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
@click.option("--force-parse", is_flag=True, help="Re-parse all pages (delete existing chunks)")
@click.option("--reindex", is_flag=True, help="Clear checkpoints and reindex all chunks from scratch")
def pipeline(
    spaces: str | None,
    verbose: bool,
    force_parse: bool,
    reindex: bool,
) -> None:
    """Run full sync pipeline: download -> parse -> index.

    This command runs all steps in a single process, sharing the same
    database connection. Use this for GCP deployments where separate
    jobs cannot share state.

    By default, already-indexed chunks are skipped (resume mode).
    Use --reindex to clear checkpoints and start from scratch.
    """
    asyncio.run(_pipeline(spaces, verbose, force_parse, reindex))


async def _pipeline(
    spaces: str | None,
    verbose: bool,
    force_parse: bool,
    reindex: bool,
) -> None:
    """Async implementation of pipeline command."""
    from knowledge_base.chunking.parser import PageParser
    from knowledge_base.confluence.downloader import ConfluenceDownloader
    from knowledge_base.db.database import async_session_maker, init_db
    from knowledge_base.graph.graphiti_indexer import GraphitiIndexer

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Parse space keys
    space_list: list[str] | None = None
    if spaces:
        space_list = [s.strip() for s in spaces.split(",") if s.strip()]

    if not space_list and not settings.confluence_space_list:
        click.echo("Error: No spaces specified. Use --spaces or set CONFLUENCE_SPACE_KEYS.", err=True)
        sys.exit(1)

    # Step 1: Download from Confluence
    click.echo("\n" + "=" * 60)
    click.echo("STEP 1: Downloading from Confluence")
    click.echo("=" * 60)

    # index_to_graphiti=False because Step 3 handles indexing separately.
    # With it True, the downloader holds a SQLAlchemy session open while
    # simultaneously writing checkpoints via raw aiosqlite, causing
    # SQLite "database is locked" errors.
    downloader = ConfluenceDownloader(index_to_graphiti=False)
    try:
        download_stats = await downloader.sync_all_spaces(
            space_keys=space_list,
            force_update=False,
            verbose=verbose,
        )
        click.echo(f"\nDownload complete!")
        click.echo(f"  New pages: {download_stats['new']}")
        click.echo(f"  Updated pages: {download_stats['updated']}")
        click.echo(f"  Skipped (unchanged): {download_stats['skipped']}")
        click.echo(f"  Errors: {download_stats['errors']}")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        sys.exit(1)

    # Step 2: Parse into chunks
    click.echo("\n" + "=" * 60)
    click.echo("STEP 2: Parsing pages into chunks")
    click.echo("=" * 60)

    parser = PageParser()
    space_key = space_list[0] if space_list else None
    parse_stats = await parser.parse_all_pages(
        space_key=space_key,
        force=force_parse,
        verbose=verbose,
    )

    click.echo(f"\nParsing complete!")
    click.echo(f"  Pages processed: {parse_stats['pages']}")
    click.echo(f"  Chunks created: {parse_stats['chunks']}")
    click.echo(f"  Errors: {parse_stats['errors']}")

    # Show chunk statistics
    chunk_stats = await parser.get_stats(space_key)
    click.echo(f"\nChunk Statistics:")
    click.echo(f"  Total chunks: {chunk_stats['total_chunks']}")
    click.echo(f"  Pages with chunks: {chunk_stats['pages_with_chunks']}")
    click.echo(f"  Average chunk size: {chunk_stats['average_chunk_size']} chars")

    # Step 3: Index into Graphiti
    click.echo("\n" + "=" * 60)
    click.echo("STEP 3: Indexing chunks into Graphiti")
    click.echo("=" * 60)

    indexer = GraphitiIndexer()

    def progress_callback(indexed: int, total: int) -> None:
        if verbose:
            click.echo(f"  Indexed {indexed}/{total} chunks")
        else:
            progress = indexed / total * 100
            click.echo(f"\rProgress: {progress:.1f}% ({indexed}/{total})", nl=False)

    # Query chunks inside a session, then close it before indexing.
    # This avoids SQLite "database is locked" errors when the indexer
    # opens its own session for checkpoint writes.
    try:
        click.echo("Indexing chunks to Graphiti...")

        from sqlalchemy import delete, func, select
        from sqlalchemy.orm import selectinload
        from knowledge_base.db.models import Chunk, RawPage, IndexingCheckpoint
        from knowledge_base.vectorstore.indexer import ChunkData
        import json

        # If reindexing, clear checkpoints first so all chunks are reprocessed
        if reindex:
            async with async_session_maker() as session:
                if space_key:
                    # Clear checkpoints only for chunks in the target space
                    space_chunk_ids = (
                        select(Chunk.chunk_id)
                        .join(RawPage, Chunk.page_id == RawPage.page_id)
                        .where(RawPage.space_key == space_key)
                    )
                    await session.execute(
                        delete(IndexingCheckpoint).where(
                            IndexingCheckpoint.chunk_id.in_(space_chunk_ids)
                        )
                    )
                else:
                    await session.execute(delete(IndexingCheckpoint))
                await session.commit()
            click.echo("Cleared indexing checkpoints for full reindex.")

        chunk_data_list = []
        async with async_session_maker() as session:
            query = (
                select(Chunk)
                .join(RawPage, Chunk.page_id == RawPage.page_id)
                .options(selectinload(Chunk.page))
                .where(RawPage.status == "active")
            )
            if space_key:
                query = query.where(RawPage.space_key == space_key)

            # Always skip already-indexed chunks (resume by default)
            indexed_subquery = (
                select(IndexingCheckpoint.chunk_id).where(
                    IndexingCheckpoint.status == "indexed"
                )
            )
            query = query.where(Chunk.chunk_id.notin_(indexed_subquery))

            indexed_count_result = await session.execute(
                select(func.count()).select_from(IndexingCheckpoint).where(
                    IndexingCheckpoint.status == "indexed"
                )
            )
            indexed_count = indexed_count_result.scalar() or 0
            if indexed_count > 0:
                click.echo(
                    f"Resuming: {indexed_count} chunks already indexed, skipping them"
                )

            result = await session.execute(query)
            chunks = result.scalars().all()

            for chunk in chunks:
                chunk_data = ChunkData(
                    chunk_id=chunk.chunk_id,
                    content=chunk.content,
                    page_id=chunk.page_id,
                    page_title=chunk.page_title,
                    chunk_index=chunk.chunk_index,
                    space_key=chunk.page.space_key if chunk.page else "",
                    url=chunk.page.url if chunk.page else "",
                    author=chunk.page.author if chunk.page else "",
                    created_at=chunk.page.created_at.isoformat() if chunk.page and chunk.page.created_at else "",
                    updated_at=chunk.page.updated_at.isoformat() if chunk.page and chunk.page.updated_at else "",
                    chunk_type=chunk.chunk_type or "text",
                    parent_headers=json.dumps(chunk.parent_headers) if chunk.parent_headers else "[]",
                )
                chunk_data_list.append(chunk_data)
        count = await indexer.index_chunks_direct(chunk_data_list, progress_callback)

        if not verbose:
            click.echo()  # New line after progress

        click.echo(f"\nIndexing complete!")
        click.echo(f"  Chunks indexed: {count}")

        # Show stats
        stats_count = await indexer.get_chunk_count()
        click.echo(f"  Total in index: {stats_count}")

    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        click.echo(f"\nError: {e}", err=True)
        sys.exit(1)

    # Final summary
    click.echo("\n" + "=" * 60)
    click.echo("PIPELINE COMPLETE")
    click.echo("=" * 60)
    click.echo(f"  Pages downloaded: {download_stats['new'] + download_stats['updated']}")
    click.echo(f"  Chunks parsed: {parse_stats['chunks']}")
    click.echo(f"  Chunks indexed: {count}")


# =============================================================================
# KEBOOLA COMMANDS
# =============================================================================


@cli.command(name="keboola-info")
@click.option(
    "--table-id",
    "-t",
    help="Keboola table ID to inspect (defaults to KEBOOLA_TABLE_ID)",
)
def keboola_info(table_id: str | None) -> None:
    """Show information about a Keboola Storage table.

    Displays table metadata (columns, row count) and a preview
    of the first few rows with parsed metadata.
    """
    from knowledge_base.keboola.client import KeboolaClient
    from knowledge_base.keboola.downloader import KeboolaDownloader

    if not settings.KEBOOLA_API_TOKEN:
        click.echo("Error: KEBOOLA_API_TOKEN not set.", err=True)
        sys.exit(1)
    if not settings.KEBOOLA_API_URL:
        click.echo("Error: KEBOOLA_API_URL not set.", err=True)
        sys.exit(1)

    effective_table_id = table_id or settings.KEBOOLA_TABLE_ID
    if not effective_table_id:
        click.echo("Error: No table ID. Use --table-id or set KEBOOLA_TABLE_ID.", err=True)
        sys.exit(1)

    client = KeboolaClient()

    try:
        info = client.get_table_detail(effective_table_id)
    except Exception as exc:
        logger.error("Failed to fetch table detail: %s", type(exc).__name__)
        click.echo("Error: Could not retrieve table details. Check credentials and table ID.", err=True)
        sys.exit(1)

    click.echo(f"\nTable: {effective_table_id}")
    click.echo(f"  Columns: {info.get('columns', [])}")
    click.echo(f"  Rows: {info.get('rowsCount', 'unknown')}")
    click.echo(f"  Data size: {info.get('dataSizeBytes', 'unknown')} bytes")
    click.echo(f"  Last import: {info.get('lastImportDate', 'unknown')}")
    click.echo(f"  Last change: {info.get('lastChangeDate', 'unknown')}")

    # Show sync state
    asyncio.run(_show_keboola_sync_state(effective_table_id))

    # Show first 3 rows with parsed metadata
    click.echo(f"\nSample rows (first 3):")
    try:
        for i, row in enumerate(client.iter_table_rows(effective_table_id)):
            if i >= 3:
                break
            text_preview = row.get("text", "")[:100]
            metadata = row.get("metadata", "")
            source_name, page_id = KeboolaDownloader._parse_metadata(metadata)
            click.echo(f"\n  Row {i}:")
            click.echo(f"    metadata: {metadata}")
            click.echo(f"    parsed -> source={source_name}, page_id={page_id}")
            click.echo(f"    text: {text_preview}...")
    except Exception as exc:
        logger.error("Failed to fetch sample rows: %s", type(exc).__name__)
        click.echo("Error: Could not retrieve sample rows. Check credentials and table ID.", err=True)
        sys.exit(1)


async def _show_keboola_sync_state(table_id: str) -> None:
    """Show last sync state for a table."""
    from knowledge_base.db.database import init_db
    from knowledge_base.keboola.downloader import KeboolaDownloader

    await init_db()
    downloader = KeboolaDownloader()
    last_sync = await downloader.get_last_sync_time(table_id)
    if last_sync:
        click.echo(f"  Last sync: {last_sync.isoformat()}")
    else:
        click.echo("  Last sync: never")


@cli.command(name="keboola-sync")
@click.option(
    "--table-id",
    "-t",
    help="Keboola table ID to sync (defaults to KEBOOLA_TABLE_ID)",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
@click.option("--dry-run", is_flag=True, help="Fetch and map data without indexing")
@click.option(
    "--reindex",
    is_flag=True,
    help="Clear checkpoints and sync state, reprocess all chunks",
)
@click.option(
    "--sample-size",
    type=int,
    default=5,
    help="Number of sample chunks to show in dry-run mode",
)
def keboola_sync(
    table_id: str | None,
    verbose: bool,
    dry_run: bool,
    reindex: bool,
    sample_size: int,
) -> None:
    """Sync data from Keboola Storage table into the knowledge graph.

    Fetches pre-chunked data from a Keboola Storage table, maps it to
    ChunkData format, and indexes it to Graphiti (Neo4j knowledge graph).

    Supports incremental sync: only rows modified since the last successful
    sync are exported and processed.

    Requires KEBOOLA_API_TOKEN and KEBOOLA_API_URL to be set.
    """
    asyncio.run(_keboola_sync(table_id, verbose, dry_run, reindex, sample_size))


async def _keboola_sync(
    table_id: str | None,
    verbose: bool,
    dry_run: bool,
    reindex: bool,
    sample_size: int = 5,
) -> None:
    """Async implementation of keboola-sync command."""
    from sqlalchemy import delete, func, select

    from knowledge_base.db.database import async_session_maker, init_db
    from knowledge_base.db.models import IndexingCheckpoint
    from knowledge_base.graph.graphiti_indexer import GraphitiIndexer
    from knowledge_base.keboola.downloader import KeboolaDownloader

    # Validate required settings
    if not settings.KEBOOLA_API_TOKEN:
        click.echo("Error: KEBOOLA_API_TOKEN not set.", err=True)
        sys.exit(1)
    if not settings.KEBOOLA_API_URL:
        click.echo("Error: KEBOOLA_API_URL not set.", err=True)
        sys.exit(1)

    effective_table_id = table_id or settings.KEBOOLA_TABLE_ID
    if not effective_table_id:
        click.echo(
            "Error: No table ID. Use --table-id or set KEBOOLA_TABLE_ID.",
            err=True,
        )
        sys.exit(1)

    await init_db()
    downloader = KeboolaDownloader()

    # Step 1: Check last sync time for incremental export
    click.echo("\n" + "=" * 60)
    click.echo("STEP 1: Fetching data from Keboola Storage")
    click.echo("=" * 60)

    changed_since: str | None = None
    if reindex:
        # Clear Keboola-specific checkpoints and sync state
        async with async_session_maker() as session:
            await session.execute(
                delete(IndexingCheckpoint).where(
                    IndexingCheckpoint.chunk_id.like("kbc_%")
                )
            )
            from knowledge_base.db.models import KeboolaSyncState

            await session.execute(
                delete(KeboolaSyncState).where(
                    KeboolaSyncState.source_id == effective_table_id
                )
            )
            await session.commit()
        click.echo("Cleared Keboola checkpoints and sync state for full reindex.")
    else:
        last_sync = await downloader.get_last_sync_time(effective_table_id)
        if last_sync:
            changed_since = last_sync.isoformat()
            click.echo(f"Incremental sync since: {changed_since}")
        else:
            click.echo("First sync: full export")

    # Show table info if verbose
    if verbose:
        info = downloader.get_table_info(effective_table_id)
        click.echo(f"  Table: {effective_table_id}")
        click.echo(f"  Total rows: {info.get('rowsCount', 'unknown')}")
        click.echo(f"  Columns: {info.get('columns', [])}")

    chunks = downloader.fetch_chunks(
        effective_table_id,
        changed_since=changed_since,
    )
    click.echo(f"\nFetched and mapped {len(chunks)} chunks from Keboola")

    if not chunks:
        click.echo("No new data to index.")
        return

    if dry_run:
        click.echo(f"\n[DRY RUN] Would index the following (showing {min(sample_size, len(chunks))} of {len(chunks)}):")
        for i, chunk in enumerate(chunks[:sample_size]):
            click.echo(
                f"  {i + 1}. {chunk.chunk_id}: {chunk.page_title} "
                f"({len(chunk.content)} chars)"
            )
        if len(chunks) > sample_size:
            click.echo(f"  ... and {len(chunks) - sample_size} more")
        return

    # Step 2: Filter already-indexed chunks (crash resume)
    click.echo("\n" + "=" * 60)
    click.echo("STEP 2: Indexing chunks to Graphiti")
    click.echo("=" * 60)

    async with async_session_maker() as session:
        indexed_subquery = select(IndexingCheckpoint.chunk_id).where(
            IndexingCheckpoint.status == "indexed"
        )
        result = await session.execute(indexed_subquery)
        already_indexed = {row[0] for row in result.all()}

    if already_indexed:
        before = len(chunks)
        chunks = [c for c in chunks if c.chunk_id not in already_indexed]
        skipped = before - len(chunks)
        if skipped > 0:
            click.echo(f"Resuming: skipping {skipped} already-indexed chunks")

    if not chunks:
        click.echo("All chunks already indexed.")
        await downloader.save_sync_state(effective_table_id, 0)
        return

    indexer = GraphitiIndexer()

    def progress_callback(indexed: int, total: int) -> None:
        if verbose:
            click.echo(f"  Indexed {indexed}/{total} chunks")
        else:
            progress = indexed / total * 100
            click.echo(f"\rProgress: {progress:.1f}% ({indexed}/{total})", nl=False)

    count = await indexer.index_chunks_direct(chunks, progress_callback)

    if not verbose:
        click.echo()  # New line after progress

    click.echo(f"\nIndexing complete!")
    click.echo(f"  Chunks indexed: {count}")

    stats_count = await indexer.get_chunk_count()
    click.echo(f"  Total in index: {stats_count}")

    # Step 3: Save sync state
    await downloader.save_sync_state(effective_table_id, count)
    click.echo(f"  Sync state saved for next incremental run")

    # Final summary
    click.echo("\n" + "=" * 60)
    click.echo("KEBOOLA SYNC COMPLETE")
    click.echo("=" * 60)
    click.echo(f"  Chunks indexed: {count}")
    click.echo(f"  Total in graph: {stats_count}")


@cli.command(name="keboola-batch-import")
@click.option(
    "--table-id",
    "-t",
    help="Keboola table ID to fetch chunks from (defaults to KEBOOLA_TABLE_ID)",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Prepare JSONL without submitting batch job",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume from last checkpoint",
)
@click.option(
    "--clear-graph",
    is_flag=True,
    help="Clear existing graph before import",
)
@click.option(
    "--sample-size",
    type=int,
    default=0,
    help="Number of chunks to process (for testing, 0=all)",
)
def keboola_batch_import(
    table_id: str | None,
    verbose: bool,
    dry_run: bool,
    resume: bool,
    clear_graph: bool,
    sample_size: int,
) -> None:
    """Batch-import Keboola data into the knowledge graph via Gemini Batch API.

    Fetches pre-chunked data from a Keboola Storage table, extracts entities
    and relationships using the Gemini Batch API (1 LLM call per chunk instead
    of 7-20), resolves entities, computes embeddings, and bulk-loads into Neo4j
    in Graphiti-compatible schema.

    Requires KEBOOLA_API_TOKEN, KEBOOLA_API_URL, and BATCH_GCS_BUCKET to be set.
    """
    asyncio.run(
        _keboola_batch_import(
            table_id, verbose, dry_run, resume, clear_graph, sample_size
        )
    )


async def _keboola_batch_import(
    table_id: str | None,
    verbose: bool,
    dry_run: bool,
    resume: bool,
    clear_graph: bool,
    sample_size: int,
) -> None:
    """Async implementation of keboola-batch-import command."""
    from knowledge_base.batch.pipeline import BatchImportPipeline
    from knowledge_base.db.database import init_db
    from knowledge_base.keboola.client import KeboolaClient
    from knowledge_base.keboola.downloader import KeboolaDownloader

    # Validate required settings (fail fast)
    missing = []
    if not settings.KEBOOLA_API_TOKEN:
        missing.append("KEBOOLA_API_TOKEN")
    if not settings.KEBOOLA_API_URL:
        missing.append("KEBOOLA_API_URL")
    if not settings.BATCH_GCS_BUCKET:
        missing.append("BATCH_GCS_BUCKET")
    if missing:
        click.echo(
            f"Error: Missing required environment variables: {', '.join(missing)}",
            err=True,
        )
        sys.exit(1)

    effective_table_id = table_id or settings.KEBOOLA_TABLE_ID
    if not effective_table_id:
        click.echo(
            "Error: No table ID. Use --table-id or set KEBOOLA_TABLE_ID.",
            err=True,
        )
        sys.exit(1)

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    await init_db()

    # Step 1: Fetch chunks from Keboola
    click.echo("\n" + "=" * 60)
    click.echo("STEP 1: Fetching chunks from Keboola Storage")
    click.echo("=" * 60)

    downloader = KeboolaDownloader()
    chunks = downloader.fetch_chunks(effective_table_id)
    click.echo(f"Fetched {len(chunks)} chunks from table {effective_table_id}")

    if not chunks:
        click.echo("No chunks to process.")
        return

    # Step 2: Truncate to sample size if requested
    if sample_size > 0:
        original_count = len(chunks)
        chunks = chunks[:sample_size]
        click.echo(
            f"Sample mode: truncated {original_count} chunks to {len(chunks)}"
        )

    # Step 3: Run batch import pipeline
    click.echo("\n" + "=" * 60)
    click.echo("STEP 2: Running batch import pipeline")
    click.echo("=" * 60)

    pipeline = BatchImportPipeline()
    result = await pipeline.run(
        chunks=chunks,
        resume=resume,
        clear_graph=clear_graph,
        dry_run=dry_run,
    )

    # Print summary
    click.echo("\n" + "=" * 60)
    click.echo("BATCH IMPORT COMPLETE")
    click.echo("=" * 60)
    click.echo(f"  Chunks processed: {result.get('chunks_total', len(chunks))}")
    click.echo(f"  Entities extracted: {result.get('entities_extracted', 0)}")
    click.echo(f"  Relationships extracted: {result.get('relationships_extracted', 0)}")
    click.echo(f"  Entities resolved: {result.get('entities_resolved', 0)}")
    click.echo(f"  Relationships resolved: {result.get('relationships_resolved', 0)}")
    if dry_run:
        click.echo(f"  JSONL URI: {result.get('input_uri', 'N/A')}")
        click.echo("  [DRY RUN] Batch job was NOT submitted.")
    else:
        click.echo(f"  Neo4j nodes written: {result.get('nodes_written', 0)}")
        click.echo(f"  Neo4j edges written: {result.get('edges_written', 0)}")


# =============================================================================
# FUZZY ENTITY MERGE
# =============================================================================


@cli.command(name="fuzzy-merge")
@click.option("--dry-run", is_flag=True, help="Report candidates without applying merges")
@click.option("--threshold", type=float, default=None, help="Override similarity threshold (default from config)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
def fuzzy_merge(dry_run: bool, threshold: float | None, verbose: bool) -> None:
    """Find and merge near-duplicate entities in the knowledge graph."""
    asyncio.run(_fuzzy_merge(dry_run, threshold, verbose))


async def _fuzzy_merge(dry_run: bool, threshold: float | None, verbose: bool) -> None:
    """Async implementation of fuzzy-merge command.

    Connects to Neo4j, fetches all Entity nodes with name embeddings,
    groups by entity_type, computes pairwise cosine similarity, and
    merges near-duplicates (redirect edges + delete duplicate node).
    """
    import math
    from collections import defaultdict

    from neo4j import AsyncGraphDatabase

    from knowledge_base.batch.resolver import _cosine_similarity, _UnionFind

    similarity_threshold = threshold if threshold is not None else settings.BATCH_ENTITY_SIMILARITY_THRESHOLD

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    click.echo("Fuzzy Entity Merge")
    click.echo("=" * 60)
    click.echo(f"  Neo4j URI: {settings.NEO4J_URI}")
    click.echo(f"  Similarity threshold: {similarity_threshold}")
    click.echo(f"  Mode: {'DRY RUN' if dry_run else 'APPLY'}")
    click.echo("=" * 60)

    if not settings.NEO4J_URI or not settings.NEO4J_PASSWORD:
        click.echo("Error: NEO4J_URI and NEO4J_PASSWORD are required.", err=True)
        sys.exit(1)

    driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )

    try:
        # Step 1: Get entity type counts (no embeddings loaded yet)
        click.echo("\nStep 1: Discovering entity types...")
        max_type_size = settings.BATCH_FUZZY_MERGE_BATCH_SIZE
        async with driver.session() as session:
            result = await session.run(
                "MATCH (e:Entity) WHERE e.name_embedding IS NOT NULL "
                "RETURN coalesce(e.entity_type, head([l IN labels(e) WHERE l <> 'Entity'])) AS entity_type, count(e) AS cnt "
                "ORDER BY cnt DESC"
            )
            type_counts = [(r["entity_type"] or "unknown", r["cnt"]) async for r in result]

        total_entities = sum(c for _, c in type_counts)
        click.echo(f"  {len(type_counts)} entity types, {total_entities} total entities with embeddings")
        for etype, cnt in type_counts:
            flag = " [SKIP - too large for pairwise]" if cnt > max_type_size else ""
            click.echo(f"    {etype}: {cnt}{flag}")

        # Step 2: Process each type independently (one at a time to control memory)
        click.echo("\nStep 2: Computing pairwise similarities per type...")
        all_candidates: list[dict] = []
        total_merged = 0
        total_edges_redirected = 0

        for etype, cnt in type_counts:
            if cnt <= 1:
                continue
            if cnt > max_type_size:
                click.echo(f"  Skipping {etype} ({cnt} entities > {max_type_size} limit)")
                continue

            click.echo(f"  Processing {etype} ({cnt} entities)...")

            # Fetch entities for this type only
            async with driver.session() as session:
                result = await session.run(
                    "MATCH (e:Entity) WHERE e.name_embedding IS NOT NULL "
                    "AND (e.entity_type = $etype OR ($etype IN labels(e))) "
                    "RETURN e.uuid AS uuid, e.name AS name, "
                    "e.name_embedding AS name_embedding",
                    etype=etype,
                )
                ents = [
                    {"uuid": r["uuid"], "name": r["name"], "embedding": list(r["name_embedding"])}
                    async for r in result
                ]

            n = len(ents)
            uf = _UnionFind(n)
            type_candidates: list[dict] = []

            for i in range(n):
                for j in range(i + 1, n):
                    sim = _cosine_similarity(ents[i]["embedding"], ents[j]["embedding"])
                    if sim >= similarity_threshold:
                        uf.union(i, j)
                        type_candidates.append({
                            "entity_a": ents[i]["name"], "uuid_a": ents[i]["uuid"],
                            "entity_b": ents[j]["name"], "uuid_b": ents[j]["uuid"],
                            "entity_type": etype, "similarity": sim,
                        })

            all_candidates.extend(type_candidates)
            click.echo(f"    Found {len(type_candidates)} merge candidates")

            # Apply merges for this type if not dry-run
            if not dry_run and type_candidates:
                clusters: dict[int, list[int]] = defaultdict(list)
                for i in range(n):
                    clusters[uf.find(i)].append(i)

                for members in clusters.values():
                    if len(members) <= 1:
                        continue
                    canonical_idx = max(members, key=lambda i: len(ents[i]["name"]))
                    canonical_uuid = ents[canonical_idx]["uuid"]
                    for idx in members:
                        if idx == canonical_idx:
                            continue
                        dup = ents[idx]
                        async with driver.session() as session:
                            r = await session.run(
                                "MATCH (d:Entity {uuid: $d})-[r:RELATES_TO]->(t) WHERE t.uuid <> $c "
                                "MERGE (:Entity {uuid: $c})-[:RELATES_TO]->(t) DELETE r RETURN count(r) AS n",
                                d=dup["uuid"], c=canonical_uuid)
                            out = (await r.single())["n"]
                            r = await session.run(
                                "MATCH (s)-[r:RELATES_TO]->(d:Entity {uuid: $d}) WHERE s.uuid <> $c "
                                "MERGE (s)-[:RELATES_TO]->(:Entity {uuid: $c}) DELETE r RETURN count(r) AS n",
                                d=dup["uuid"], c=canonical_uuid)
                            inc = (await r.single())["n"]
                            r = await session.run(
                                "MATCH (ep)-[r:MENTIONS]->(d:Entity {uuid: $d}) "
                                "MERGE (ep)-[:MENTIONS]->(:Entity {uuid: $c}) DELETE r RETURN count(r) AS n",
                                d=dup["uuid"], c=canonical_uuid)
                            men = (await r.single())["n"]
                            await session.run("MATCH (d:Entity {uuid: $d}) DETACH DELETE d", d=dup["uuid"])
                        total_merged += 1
                        total_edges_redirected += out + inc + men
                        if verbose:
                            click.echo(f"      Merged {dup['name']!r} -> {ents[canonical_idx]['name']!r} ({out+inc+men} edges)")

            del ents  # Free memory before next type

        # Summary
        click.echo(f"\nTotal merge candidates: {len(all_candidates)}")
        if all_candidates:
            click.echo("\nTop merge candidates:")
            for mc in sorted(all_candidates, key=lambda x: -x["similarity"])[:50]:
                click.echo(
                    f"  [{mc['similarity']:.4f}] {mc['entity_a']!r} <-> {mc['entity_b']!r} "
                    f"(type={mc['entity_type']})"
                )
            if len(all_candidates) > 50:
                click.echo(f"  ... and {len(all_candidates) - 50} more")

        if dry_run:
            click.echo(f"\n[DRY RUN] {len(all_candidates)} pairs would be merged. No changes applied.")
        else:
            click.echo(f"\nMerge complete:")
            click.echo(f"  Entities merged: {total_merged}")
            click.echo(f"  Edges redirected: {total_edges_redirected}")

    finally:
        await driver.close()


# =============================================================================
# COMMUNITY DETECTION
# =============================================================================


@cli.command(name="build-communities")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
def build_communities(verbose: bool) -> None:
    """Build topic communities using Graphiti's label propagation."""
    asyncio.run(_build_communities(verbose))


async def _build_communities(verbose: bool) -> None:
    """Async implementation of build-communities command."""
    from knowledge_base.graph.graphiti_client import get_graphiti_client
    from knowledge_base.graph.vector_indices import create_vector_indices

    click.echo("Connecting to Graphiti...")
    client = get_graphiti_client()
    graphiti = await client.get_client()

    group_ids = [settings.GRAPH_GROUP_ID]
    click.echo(f"Building communities for group_ids={group_ids}...")

    communities, community_edges = await graphiti.build_communities(group_ids=group_ids)

    click.echo(f"Built {len(communities)} communities, {len(community_edges)} community edges")

    if verbose:
        for c in communities[:20]:
            click.echo(f"  - {c.name}: {c.summary[:100] if c.summary else '(no summary)'}...")

    # Ensure vector indices exist (including community index)
    click.echo("Creating/verifying vector indices...")
    await create_vector_indices(graphiti.driver)

    click.echo("Done!")


# =============================================================================
# SEARCH COMMANDS (Phase 05.5)
# =============================================================================


@cli.group()
def search() -> None:
    """Hybrid search commands (BM25 + vector)."""
    pass


@search.command(name="query")
@click.argument("query_text")
@click.option("--method", "-m", type=click.Choice(["hybrid", "bm25", "vector"]), default="hybrid", help="Search method (all use Graphiti now)")
@click.option("--top", "-k", type=int, default=5, help="Number of results to show")
@click.option("--weights", "-w", help="DEPRECATED: Graphiti handles weights internally")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
def query(query_text: str, method: str, top: int, weights: str | None, verbose: bool) -> None:
    """Search the knowledge base with the given query."""
    asyncio.run(_query(query_text, method, top, weights, verbose))


async def _query(query_text: str, method: str, top: int, weights: str | None, verbose: bool) -> None:
    """Async implementation of query command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.search import HybridRetriever

    await init_db()

    if weights:
        click.echo("Note: --weights is deprecated. Graphiti handles weights internally.")

    click.echo(f"Query: '{query_text}'")
    click.echo(f"Method: hybrid (Graphiti)")
    click.echo("-" * 60)

    # All methods now use Graphiti hybrid search
    retriever = HybridRetriever()

    health = await retriever.check_health()
    if verbose:
        click.echo(f"Health: {health}")

    if not health.get("graphiti_healthy"):
        click.echo("Warning: Graphiti may not be fully available.")

    results = await retriever.search(query_text, k=top)
    click.echo(f"\nSearch Results ({len(results)} found):\n")

    for i, r in enumerate(results, 1):
        click.echo(f"{i}. [{r.score:.4f}] {r.page_title}")
        if verbose:
            click.echo(f"   Chunk ID: {r.chunk_id}")
            click.echo(f"   Content: {r.content[:150]}...")
        click.echo()


@search.command(name="stats")
def search_stats() -> None:
    """Show search index statistics."""
    asyncio.run(_search_stats())


async def _search_stats() -> None:
    """Async implementation of search stats command."""
    from knowledge_base.db.database import init_db
    from knowledge_base.search import HybridRetriever

    await init_db()

    click.echo("Search Index Statistics")
    click.echo("=" * 50)

    # Graphiti stats
    retriever = HybridRetriever()
    health = await retriever.check_health()

    click.echo(f"\nGraphiti Search Backend:")
    click.echo(f"  Enabled: {health.get('graphiti_enabled', False)}")
    click.echo(f"  Healthy: {health.get('graphiti_healthy', False)}")
    click.echo(f"  Backend: {health.get('backend', 'unknown')}")

    click.echo(f"\nNote: Graphiti provides built-in hybrid search (BM25 + vector + graph).")


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
