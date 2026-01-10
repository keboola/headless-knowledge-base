"""Two-stage archival pipeline for knowledge lifecycle management."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker
from knowledge_base.db.models import (
    ArchivedChunk,
    ArchivedChunkQuality,
    Chunk,
    ChunkQuality,
    UserFeedback,
)

logger = logging.getLogger(__name__)


async def deprecate_chunk(
    chunk_id: str,
    reason: str,
    replacement_chunk_id: str | None = None,
) -> bool:
    """Mark a specific chunk as deprecated."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(ChunkQuality).where(ChunkQuality.chunk_id == chunk_id)
        )
        quality = result.scalar_one_or_none()

        if quality:
            quality.status = "deprecated"
            quality.deprecated_at = datetime.utcnow()
            quality.deprecation_reason = reason
            quality.quality_score = 0  # Immediately remove from results
            await session.commit()

            logger.info(f"Chunk deprecated: {chunk_id}, reason: {reason}")
            return True

        return False


async def move_to_cold_storage(
    session: AsyncSession,
    chunk: Chunk,
    quality: ChunkQuality,
) -> ArchivedChunk:
    """Move a chunk to cold storage (archived_chunks table)."""
    # Count total feedback for this chunk
    feedback_count_result = await session.execute(
        select(func.count(UserFeedback.id)).where(
            UserFeedback.chunk_id == chunk.chunk_id
        )
    )
    total_feedback = feedback_count_result.scalar() or 0

    # Create archived chunk record
    archived_chunk = ArchivedChunk(
        chunk_id=chunk.chunk_id,
        page_id=chunk.page_id,
        content=chunk.content,
        chunk_type=chunk.chunk_type,
        chunk_index=chunk.chunk_index,
        parent_headers=chunk.parent_headers,
        page_title=chunk.page_title,
        original_created_at=chunk.created_at,
        archive_reason=quality.deprecation_reason or "Low quality score",
        final_quality_score=quality.quality_score,
        original_page_file_path=chunk.page.file_path if chunk.page else "",
    )
    session.add(archived_chunk)

    # Create archived quality record
    archived_quality = ArchivedChunkQuality(
        chunk_id=chunk.chunk_id,
        final_quality_score=quality.quality_score,
        total_access_count=quality.access_count,
        total_feedback_count=total_feedback,
    )
    session.add(archived_quality)

    # Update quality status
    quality.status = "cold_storage"
    quality.cold_archived_at = datetime.utcnow()

    logger.info(f"Chunk moved to cold storage: {chunk.chunk_id}")
    return archived_chunk


async def export_to_hard_archive(
    chunk_ids: list[str],
    archive_path: Path | None = None,
) -> dict:
    """Export cold-archived chunks to JSON files, then delete from DB."""
    if archive_path is None:
        archive_path = Path(settings.HARD_ARCHIVE_PATH)

    exported = []

    async with async_session_maker() as session:
        for chunk_id in chunk_ids:
            # Get archived chunk data
            chunk_result = await session.execute(
                select(ArchivedChunk).where(ArchivedChunk.chunk_id == chunk_id)
            )
            archived_chunk = chunk_result.scalar_one_or_none()
            if not archived_chunk:
                continue

            # Get archived quality data
            quality_result = await session.execute(
                select(ArchivedChunkQuality).where(
                    ArchivedChunkQuality.chunk_id == chunk_id
                )
            )
            archived_quality = quality_result.scalar_one_or_none()

            # Get feedback history
            feedback_result = await session.execute(
                select(UserFeedback).where(UserFeedback.chunk_id == chunk_id)
            )
            feedback_records = feedback_result.scalars().all()
            feedback_history = [
                {
                    "type": f.feedback_type,
                    "user": f.slack_username,
                    "comment": f.comment,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in feedback_records
            ]

            # Create comprehensive archive record
            archive_record = {
                "chunk_id": chunk_id,
                "content": archived_chunk.content,
                "metadata": {
                    "page_id": archived_chunk.page_id,
                    "page_title": archived_chunk.page_title,
                    "chunk_type": archived_chunk.chunk_type,
                    "chunk_index": archived_chunk.chunk_index,
                    "parent_headers": json.loads(archived_chunk.parent_headers),
                },
                "quality": {
                    "final_score": archived_quality.final_quality_score if archived_quality else 0,
                    "total_accesses": archived_quality.total_access_count if archived_quality else 0,
                    "total_feedback": archived_quality.total_feedback_count if archived_quality else 0,
                },
                "feedback_history": feedback_history,
                "timestamps": {
                    "original_created": archived_chunk.original_created_at.isoformat(),
                    "cold_archived": archived_chunk.cold_archived_at.isoformat(),
                    "hard_archived": datetime.utcnow().isoformat(),
                },
                "archive_reason": archived_chunk.archive_reason,
            }

            # Write to date-partitioned directory
            date_dir = archive_path / datetime.utcnow().strftime("%Y/%m")
            date_dir.mkdir(parents=True, exist_ok=True)
            file_path = date_dir / f"{chunk_id}.json"
            file_path.write_text(json.dumps(archive_record, indent=2))

            # Delete from cold storage tables
            await session.delete(archived_chunk)
            if archived_quality:
                await session.delete(archived_quality)

            # Update quality status to hard_archived
            quality_result = await session.execute(
                select(ChunkQuality).where(ChunkQuality.chunk_id == chunk_id)
            )
            quality = quality_result.scalar_one_or_none()
            if quality:
                quality.status = "hard_archived"
                quality.hard_archived_at = datetime.utcnow()

            exported.append(chunk_id)

        await session.commit()

    logger.info(f"Hard archived {len(exported)} chunks to {archive_path}")
    return {"exported": len(exported), "path": str(archive_path)}


async def get_cold_archived_chunks_older_than(days: int) -> list[ArchivedChunk]:
    """Get chunks that have been in cold storage longer than specified days."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    async with async_session_maker() as session:
        result = await session.execute(
            select(ArchivedChunk).where(ArchivedChunk.cold_archived_at < cutoff)
        )
        return list(result.scalars().all())


async def run_archival_pipeline() -> dict:
    """Process chunks through all archival stages."""
    stats = {
        "deprecated": 0,
        "cold_archived": 0,
        "hard_archived": 0,
        "restored": 0,
    }

    async with async_session_maker() as session:
        # Get all active and deprecated chunks with their quality
        result = await session.execute(
            select(Chunk, ChunkQuality)
            .join(ChunkQuality, Chunk.chunk_id == ChunkQuality.chunk_id)
            .where(ChunkQuality.status.in_(["active", "deprecated"]))
        )
        chunks_with_quality = result.fetchall()

        for chunk, quality in chunks_with_quality:
            old_status = quality.status

            # Move to cold storage if score < 10
            if quality.quality_score < settings.SCORE_THRESHOLD_ARCHIVE:
                await move_to_cold_storage(session, chunk, quality)
                stats["cold_archived"] += 1

            # Deprecate if score < 40 and currently active
            elif (
                quality.quality_score < settings.SCORE_THRESHOLD_DEPRECATED
                and old_status == "active"
            ):
                quality.status = "deprecated"
                quality.deprecated_at = datetime.utcnow()
                stats["deprecated"] += 1

            # Restore if score >= 70 and currently deprecated
            elif quality.quality_score >= 70 and old_status == "deprecated":
                quality.status = "active"
                quality.deprecated_at = None
                stats["restored"] += 1

        await session.commit()

    # Stage 2: Cold Storage -> Hard Archive (after configured days)
    old_cold_chunks = await get_cold_archived_chunks_older_than(
        days=settings.COLD_ARCHIVE_DAYS
    )
    if old_cold_chunks:
        result = await export_to_hard_archive(
            [c.chunk_id for c in old_cold_chunks],
        )
        stats["hard_archived"] = result["exported"]

    logger.info(
        f"Archival pipeline complete: {stats['deprecated']} deprecated, "
        f"{stats['cold_archived']} cold archived, "
        f"{stats['hard_archived']} hard archived, "
        f"{stats['restored']} restored"
    )
    return stats


async def get_archival_stats() -> dict:
    """Get statistics about archived content."""
    async with async_session_maker() as session:
        # Count by status
        result = await session.execute(
            select(
                ChunkQuality.status,
                func.count(ChunkQuality.id),
            ).group_by(ChunkQuality.status)
        )
        by_status = {row[0]: row[1] for row in result.fetchall()}

        # Count cold archived
        cold_result = await session.execute(
            select(func.count(ArchivedChunk.id))
        )
        cold_storage_count = cold_result.scalar() or 0

        return {
            "by_status": by_status,
            "cold_storage_count": cold_storage_count,
        }
