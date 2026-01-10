"""Vector indexer for embedding and storing chunks in ChromaDB.

ChromaDB is the SOURCE OF TRUTH for all knowledge data per docs/ARCHITECTURE.md.
This module provides both direct indexing (preferred) and SQLite-based indexing
(for backward compatibility during migration).
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from knowledge_base.config import settings
# NOTE: Chunk, ChunkQuality, GovernanceMetadata are DEPRECATED - use ChunkData instead
# RawPage is kept for Confluence sync tracking
from knowledge_base.db.models import Chunk, ChunkQuality, GovernanceMetadata, RawPage
from knowledge_base.vectorstore.client import ChromaClient
from knowledge_base.vectorstore.embeddings import BaseEmbeddings, get_embeddings

logger = logging.getLogger(__name__)


@dataclass
class ChunkData:
    """Data structure for a chunk to be indexed directly to ChromaDB.

    This bypasses SQLAlchemy models for direct ChromaDB indexing.
    All fields are stored as ChromaDB metadata for search filtering.
    """

    # Required fields
    chunk_id: str
    content: str
    page_id: str
    page_title: str
    chunk_index: int

    # Source info
    space_key: str = ""
    url: str = ""
    author: str = ""
    created_at: str = ""  # ISO datetime
    updated_at: str = ""  # ISO datetime

    # Chunk structure
    chunk_type: str = "text"  # text, code, table, list
    parent_headers: str = "[]"  # JSON array

    # Quality (managed natively in ChromaDB)
    quality_score: float = 100.0  # 0-100
    access_count: int = 0
    feedback_count: int = 0

    # Governance (stored in ChromaDB)
    owner: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""
    classification: str = "internal"  # public, internal, confidential

    # AI metadata
    doc_type: str = ""  # policy, how-to, reference, FAQ, quick_fact
    topics: str = "[]"  # JSON array
    audience: str = "[]"  # JSON array
    complexity: str = ""  # beginner, intermediate, advanced
    summary: str = ""

    def to_metadata(self) -> dict[str, Any]:
        """Convert to ChromaDB metadata dictionary."""
        return {
            "page_id": self.page_id,
            "page_title": self.page_title,
            "chunk_type": self.chunk_type,
            "chunk_index": self.chunk_index,
            "space_key": self.space_key,
            "url": self.url,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "parent_headers": self.parent_headers,
            "quality_score": self.quality_score,
            "access_count": self.access_count,
            "feedback_count": self.feedback_count,
            "owner": self.owner,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "classification": self.classification,
            "doc_type": self.doc_type,
            "topics": self.topics,
            "audience": self.audience,
            "complexity": self.complexity,
            "summary": self.summary[:500] if self.summary else "",
        }


def batched(iterable, n: int):
    """Yield successive n-sized chunks from iterable."""
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) == n:
            yield batch
            batch = []
    if batch:
        yield batch


class VectorIndexer:
    """Indexes chunks into ChromaDB with embeddings."""

    def __init__(
        self,
        embeddings: BaseEmbeddings | None = None,
        chroma: ChromaClient | None = None,
        batch_size: int | None = None,
    ):
        """Initialize the vector indexer.

        Args:
            embeddings: Embeddings provider (defaults to configured provider)
            chroma: ChromaDB client (defaults to new client)
            batch_size: Batch size for indexing (defaults to settings.INDEX_BATCH_SIZE)
        """
        self.embeddings = embeddings or get_embeddings()
        self.chroma = chroma or ChromaClient()
        self.batch_size = batch_size or settings.INDEX_BATCH_SIZE

    def build_metadata(self, chunk: Chunk, governance: GovernanceMetadata | None = None) -> dict[str, Any]:
        """Build ChromaDB metadata from a chunk (SQLAlchemy model).

        This method is used during migration. For new code, prefer using
        ChunkData.to_metadata() or index_chunks_direct() instead.

        Args:
            chunk: Chunk model instance
            governance: Optional governance metadata for the page

        Returns:
            Metadata dictionary for ChromaDB with all required fields
        """
        # Core identifiers
        metadata: dict[str, Any] = {
            "page_id": chunk.page_id,
            "page_title": chunk.page_title or "",
            "chunk_type": chunk.chunk_type or "text",
            "chunk_index": chunk.chunk_index,
        }

        # Structure
        metadata["parent_headers"] = chunk.parent_headers or "[]"

        # Add page-level data if available
        if chunk.page:
            metadata["space_key"] = chunk.page.space_key
            metadata["author"] = chunk.page.author_name or chunk.page.author or ""
            metadata["url"] = chunk.page.url or ""
            metadata["created_at"] = chunk.page.created_at.isoformat() if chunk.page.created_at else ""
            metadata["updated_at"] = chunk.page.updated_at.isoformat() if chunk.page.updated_at else ""
        else:
            metadata["space_key"] = ""
            metadata["author"] = ""
            metadata["url"] = ""
            metadata["created_at"] = ""
            metadata["updated_at"] = ""

        # Add chunk metadata if available (AI-generated)
        if chunk.chunk_metadata:
            metadata["topics"] = chunk.chunk_metadata.topics or "[]"  # JSON string
            metadata["doc_type"] = chunk.chunk_metadata.doc_type or ""
            metadata["audience"] = chunk.chunk_metadata.audience or "[]"  # JSON string
            metadata["complexity"] = chunk.chunk_metadata.complexity or ""
            metadata["summary"] = chunk.chunk_metadata.summary[:500] if chunk.chunk_metadata.summary else ""
        else:
            metadata["topics"] = "[]"
            metadata["doc_type"] = ""
            metadata["audience"] = "[]"
            metadata["complexity"] = ""
            metadata["summary"] = ""

        # Quality fields (ChromaDB is source of truth for these)
        if chunk.quality:
            metadata["quality_score"] = chunk.quality.quality_score
            metadata["access_count"] = chunk.quality.access_count or 0
            metadata["feedback_count"] = chunk.quality.access_count_30d or 0  # Recent access as proxy
        else:
            metadata["quality_score"] = 100.0  # Default score for new chunks
            metadata["access_count"] = 0
            metadata["feedback_count"] = 0

        # Governance fields (stored in ChromaDB)
        if governance:
            metadata["owner"] = governance.owner or ""
            metadata["reviewed_by"] = governance.reviewed_by or ""
            metadata["reviewed_at"] = governance.reviewed_at.isoformat() if governance.reviewed_at else ""
            metadata["classification"] = governance.classification or "internal"
        elif chunk.page and chunk.page.governance:
            # Fallback to page's governance relationship
            gov = chunk.page.governance
            metadata["owner"] = gov.owner or ""
            metadata["reviewed_by"] = gov.reviewed_by or ""
            metadata["reviewed_at"] = gov.reviewed_at.isoformat() if gov.reviewed_at else ""
            metadata["classification"] = gov.classification or "internal"
        else:
            metadata["owner"] = ""
            metadata["reviewed_by"] = ""
            metadata["reviewed_at"] = ""
            metadata["classification"] = "internal"

        return metadata

    async def index_chunks(
        self,
        session: AsyncSession,
        space_key: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Index all chunks (or chunks from a specific space).

        Args:
            session: Database session
            space_key: Optional space key to filter by
            progress_callback: Optional callback(indexed, total) for progress updates

        Returns:
            Number of chunks indexed
        """
        # Build query with all necessary relationships
        query = (
            select(Chunk)
            .options(
                selectinload(Chunk.page).selectinload(RawPage.governance),
                selectinload(Chunk.chunk_metadata),
                selectinload(Chunk.quality),
            )
        )

        if space_key:
            query = query.join(RawPage).where(RawPage.space_key == space_key)

        result = await session.execute(query)
        chunks = list(result.scalars().all())

        if not chunks:
            logger.info("No chunks to index")
            return 0

        total = len(chunks)
        indexed = 0

        logger.info(
            f"Indexing {total} chunks using {self.embeddings.provider_name} embeddings"
        )

        for batch in batched(chunks, self.batch_size):
            # Prepare batch data
            ids = [c.chunk_id for c in batch]
            texts = [c.content for c in batch]
            metadatas = [self.build_metadata(c) for c in batch]

            # Generate embeddings
            try:
                embeddings = await self.embeddings.embed(texts)
            except Exception as e:
                logger.error(f"Failed to generate embeddings: {e}")
                raise

            # Upsert to ChromaDB
            await self.chroma.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )

            indexed += len(batch)
            if progress_callback:
                progress_callback(indexed, total)

            logger.debug(f"Indexed {indexed}/{total} chunks")

        logger.info(f"Indexing complete: {indexed} chunks indexed")
        return indexed

    async def delete_chunks(self, chunk_ids: list[str]) -> int:
        """Delete chunks from the index.

        Args:
            chunk_ids: List of chunk IDs to delete

        Returns:
            Number of chunks deleted
        """
        if not chunk_ids:
            return 0

        await self.chroma.delete(chunk_ids)
        logger.info(f"Deleted {len(chunk_ids)} chunks from index")
        return len(chunk_ids)

    async def index_chunks_direct(
        self,
        chunks: list[ChunkData],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Index chunks directly to ChromaDB without SQLite intermediate storage.

        This is the preferred method for new code. It bypasses SQLAlchemy models
        and writes directly to ChromaDB as the source of truth.

        Args:
            chunks: List of ChunkData objects to index
            progress_callback: Optional callback(indexed, total) for progress updates

        Returns:
            Number of chunks indexed
        """
        if not chunks:
            logger.info("No chunks to index")
            return 0

        total = len(chunks)
        indexed = 0

        logger.info(
            f"Direct indexing {total} chunks using {self.embeddings.provider_name} embeddings"
        )

        for batch in batched(chunks, self.batch_size):
            # Prepare batch data
            ids = [c.chunk_id for c in batch]
            texts = [c.content for c in batch]
            metadatas = [c.to_metadata() for c in batch]

            # Generate embeddings
            try:
                embeddings = await self.embeddings.embed(texts)
            except Exception as e:
                logger.error(f"Failed to generate embeddings: {e}")
                raise

            # Upsert to ChromaDB (source of truth)
            await self.chroma.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )

            indexed += len(batch)
            if progress_callback:
                progress_callback(indexed, total)

            logger.debug(f"Direct indexed {indexed}/{total} chunks")

        logger.info(f"Direct indexing complete: {indexed} chunks indexed to ChromaDB")
        return indexed

    async def index_single_chunk(self, chunk: ChunkData) -> None:
        """Index a single chunk directly to ChromaDB.

        Convenience method for indexing one chunk at a time (e.g., quick knowledge).

        Args:
            chunk: ChunkData object to index
        """
        # Generate embedding
        embeddings = await self.embeddings.embed([chunk.content])

        # Upsert to ChromaDB
        await self.chroma.upsert(
            ids=[chunk.chunk_id],
            embeddings=embeddings,
            documents=[chunk.content],
            metadatas=[chunk.to_metadata()],
        )

        logger.info(f"Indexed single chunk: {chunk.chunk_id}")

    async def reindex(
        self,
        session: AsyncSession,
        space_key: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Delete and rebuild the index.

        Args:
            session: Database session
            space_key: Optional space key to filter by
            progress_callback: Optional callback for progress updates

        Returns:
            Number of chunks indexed
        """
        logger.info("Resetting collection for reindex")
        self.chroma.reset_collection()
        return await self.index_chunks(session, space_key, progress_callback)

    async def get_stats(self) -> dict[str, Any]:
        """Get indexing statistics.

        Returns:
            Statistics dictionary
        """
        count = await self.chroma.count()
        return {
            "indexed_chunks": count,
            "embedding_provider": self.embeddings.provider_name,
            "embedding_dimension": self.embeddings.dimension,
        }
