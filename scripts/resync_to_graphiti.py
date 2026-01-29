#!/usr/bin/env python3
"""Re-sync all documents to Graphiti.

This script indexes all pages from the database into Graphiti, the new
graph-based source of truth for the knowledge base.

Usage:
    python scripts/resync_to_graphiti.py [OPTIONS]

Examples:
    # Dry run to see what would be indexed
    python scripts/resync_to_graphiti.py --dry-run

    # Index first 10 pages as a test
    python scripts/resync_to_graphiti.py --limit 10

    # Full resync of all pages
    python scripts/resync_to_graphiti.py

    # Resync specific space
    python scripts/resync_to_graphiti.py --space ENG
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowledge_base.config import settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def resync_to_graphiti(
    space_key: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Resync all documents to Graphiti.

    Args:
        space_key: Only resync pages from this Confluence space
        limit: Maximum number of pages to process
        dry_run: If True, don't actually index, just show what would happen
        verbose: Show detailed progress

    Returns:
        Stats dict with pages, chunks, errors counts
    """
    from sqlalchemy import select

    from knowledge_base.db.database import async_session_maker, init_db
    from knowledge_base.db.models import RawPage
    from knowledge_base.graph.graphiti_indexer import GraphitiIndexer
    from knowledge_base.vectorstore.indexer import ChunkData
    from knowledge_base.chunking.markdown_chunker import MarkdownChunker

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Check Graphiti config
    if not settings.GRAPH_ENABLE_GRAPHITI:
        logger.error("GRAPH_ENABLE_GRAPHITI is disabled. Enable it to use this script.")
        return {"pages": 0, "chunks": 0, "errors": 1}

    logger.info(f"Graph backend: {settings.GRAPH_BACKEND}")
    if settings.GRAPH_BACKEND == "neo4j":
        logger.info(f"Neo4j URI: {settings.NEO4J_URI}")

    indexer = GraphitiIndexer()
    chunker = MarkdownChunker()

    stats = {"pages": 0, "chunks": 0, "errors": 0, "skipped": 0}

    async with async_session_maker() as session:
        # Get pages to index
        query = select(RawPage).where(RawPage.status == "active")
        if space_key:
            query = query.where(RawPage.space_key == space_key)
            logger.info(f"Filtering to space: {space_key}")

        query = query.order_by(RawPage.updated_at.desc())

        if limit:
            query = query.limit(limit)
            logger.info(f"Limiting to {limit} pages")

        result = await session.execute(query)
        pages = result.scalars().all()

        total_pages = len(pages)
        logger.info(f"Found {total_pages} pages to index")

        if dry_run:
            logger.info("DRY RUN - not actually indexing")
            for page in pages:
                md_path = Path(page.file_path)
                exists = md_path.exists()
                logger.info(f"  [{page.space_key}] {page.title} - file exists: {exists}")
                if exists:
                    content = md_path.read_text(encoding="utf-8")
                    chunks = chunker.chunk(content, page.page_id, page.title)
                    stats["chunks"] += len(chunks)
                stats["pages"] += 1

            logger.info(f"\nDRY RUN SUMMARY:")
            logger.info(f"  Would process {stats['pages']} pages")
            logger.info(f"  Would create ~{stats['chunks']} chunks")
            return stats

        # Process each page
        for i, page in enumerate(pages):
            try:
                # Read markdown file
                md_path = Path(page.file_path)
                if not md_path.exists():
                    if verbose:
                        logger.warning(f"Skipping {page.title}: file not found at {md_path}")
                    stats["skipped"] += 1
                    continue

                markdown_content = md_path.read_text(encoding="utf-8")
                chunks = chunker.chunk(markdown_content, page.page_id, page.title)

                if not chunks:
                    if verbose:
                        logger.info(f"Skipping {page.title}: no chunks generated")
                    stats["skipped"] += 1
                    continue

                # Build ChunkData for direct indexing
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

                # Index to Graphiti
                indexed = await indexer.index_chunks_direct(chunk_data_list)
                stats["chunks"] += indexed
                stats["pages"] += 1

                if verbose:
                    logger.info(f"  [{i+1}/{total_pages}] {page.title}: {indexed} chunks")
                else:
                    # Progress indicator
                    progress = (i + 1) / total_pages * 100
                    print(f"\rProgress: {progress:.1f}% ({i + 1}/{total_pages} pages, {stats['chunks']} chunks)", end="", flush=True)

            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error processing {page.title}: {e}")
                if verbose:
                    import traceback
                    traceback.print_exc()

        if not verbose and total_pages > 0:
            print()  # New line after progress

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Re-sync all documents to Graphiti",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Dry run to see what would be indexed
    python scripts/resync_to_graphiti.py --dry-run

    # Index first 10 pages as a test
    python scripts/resync_to_graphiti.py --limit 10

    # Full resync of all pages
    python scripts/resync_to_graphiti.py

    # Resync specific space
    python scripts/resync_to_graphiti.py --space ENG
        """,
    )
    parser.add_argument(
        "--space", "-s",
        help="Only resync pages from this Confluence space",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        help="Maximum number of pages to process",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be indexed without actually indexing",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress for each page",
    )

    args = parser.parse_args()

    # Run the resync
    stats = asyncio.run(resync_to_graphiti(
        space_key=args.space,
        limit=args.limit,
        dry_run=args.dry_run,
        verbose=args.verbose,
    ))

    # Print summary
    print("\n" + "=" * 50)
    print("RESYNC COMPLETE")
    print("=" * 50)
    print(f"  Pages processed: {stats['pages']}")
    print(f"  Chunks indexed:  {stats['chunks']}")
    print(f"  Skipped:         {stats.get('skipped', 0)}")
    print(f"  Errors:          {stats['errors']}")

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
