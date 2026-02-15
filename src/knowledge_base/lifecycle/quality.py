"""Quality scoring and usage-based decay for content chunks.

Graphiti is the SOURCE OF TRUTH for quality scores.
ChunkAccessLog is stored in SQLite/DuckDB for analytics only.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker
from knowledge_base.db.models import (
    Chunk,
    ChunkAccessLog,
    ChunkQuality,
    UserFeedback,
)

logger = logging.getLogger(__name__)


def calculate_usage_adjusted_decay(quality: ChunkQuality) -> float:
    """
    Calculate monthly decay rate based on usage patterns.

    Higher usage = slower decay, encouraging frequently-used content.
    """
    base_decay = 2.0  # Base: 2 points/month

    access_30d = quality.access_count_30d

    # Decay adjustment based on usage tiers
    if access_30d >= 50:  # High usage
        decay = base_decay * 0.25  # 0.5 points/month
    elif access_30d >= 20:  # Medium-high usage
        decay = base_decay * 0.5  # 1 point/month
    elif access_30d >= 5:  # Medium usage
        decay = base_decay * 0.75  # 1.5 points/month
    elif access_30d >= 1:  # Low usage
        decay = base_decay * 1.0  # 2 points/month
    else:  # No recent usage
        decay = base_decay * 1.5  # 3 points/month (accelerated decay)

    return max(decay, 0.25)  # Minimum 0.25 decay


async def count_recent_feedback(
    session: AsyncSession,
    chunk_id: str,
    feedback_type: str,
    days: int = 90,
) -> int:
    """Count feedback of a specific type within the last N days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await session.execute(
        select(func.count(UserFeedback.id))
        .where(UserFeedback.chunk_id == chunk_id)
        .where(UserFeedback.feedback_type == feedback_type)
        .where(UserFeedback.created_at >= cutoff)
    )
    return result.scalar() or 0


async def initialize_chunk_quality(chunk_id: str) -> ChunkQuality:
    """Initialize quality record for a new chunk."""
    async with async_session_maker() as session:
        # Check if already exists
        result = await session.execute(
            select(ChunkQuality).where(ChunkQuality.chunk_id == chunk_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        quality = ChunkQuality(
            chunk_id=chunk_id,
            quality_score=100.0,
            base_score=100.0,
            access_count=0,
            access_count_30d=0,
            current_decay_rate=2.0,
            status="active",
        )
        session.add(quality)
        await session.commit()
        await session.refresh(quality)
        return quality


async def initialize_all_chunk_quality() -> dict:
    """Initialize quality records for all chunks that don't have one."""
    stats = {"initialized": 0, "skipped": 0}

    async with async_session_maker() as session:
        # Find chunks without quality records
        result = await session.execute(
            select(Chunk.chunk_id).outerjoin(
                ChunkQuality, Chunk.chunk_id == ChunkQuality.chunk_id
            ).where(ChunkQuality.id.is_(None))
        )
        missing_chunk_ids = [row[0] for row in result.fetchall()]

        for chunk_id in missing_chunk_ids:
            quality = ChunkQuality(
                chunk_id=chunk_id,
                quality_score=100.0,
                base_score=100.0,
                access_count=0,
                access_count_30d=0,
                current_decay_rate=2.0,
                status="active",
            )
            session.add(quality)
            stats["initialized"] += 1

        await session.commit()

    logger.info(f"Initialized quality records: {stats['initialized']} new")
    return stats


async def record_chunk_access(
    chunk_id: str,
    slack_user_id: str,
    query_context: str | None = None,
) -> None:
    """Record an access to a chunk for usage tracking.

    Updates access count in Graphiti (source of truth) and logs to SQLite/DuckDB.
    """
    # 1. Update access count in Graphiti (source of truth)
    await record_chunk_access_graphiti(chunk_id)

    # 2. Log access to SQLite/DuckDB (for analytics)
    async with async_session_maker() as session:
        access_log = ChunkAccessLog(
            chunk_id=chunk_id,
            slack_user_id=slack_user_id,
            query_context=query_context,
        )
        session.add(access_log)
        await session.commit()


async def record_chunk_access_graphiti(chunk_id: str) -> None:
    """Increment access count in Graphiti (source of truth)."""
    try:
        from knowledge_base.graph.graphiti_builder import get_graphiti_builder

        builder = get_graphiti_builder()

        # Get current episode
        episode = await builder.get_chunk_episode(chunk_id)

        if episode:
            metadata = episode.get("metadata", {})
            current_access = metadata.get("access_count", 0)
            # Update access count
            await builder.update_chunk_metadata(
                chunk_id,
                {"access_count": current_access + 1},
            )
            logger.debug(f"Incremented access count in Graphiti: {chunk_id}")
        else:
            logger.warning(f"Chunk {chunk_id} not found in Graphiti for access tracking")

    except Exception as e:
        logger.warning(f"Failed to update access count in Graphiti: {e}")


async def update_rolling_access_counts() -> dict:
    """Update 30-day rolling access counts for all chunks."""
    stats = {"updated": 0}
    cutoff = datetime.utcnow() - timedelta(days=30)

    async with async_session_maker() as session:
        # Get all quality records
        result = await session.execute(select(ChunkQuality))
        quality_records = result.scalars().all()

        for quality in quality_records:
            # Count accesses in last 30 days
            count_result = await session.execute(
                select(func.count(ChunkAccessLog.id))
                .where(ChunkAccessLog.chunk_id == quality.chunk_id)
                .where(ChunkAccessLog.accessed_at >= cutoff)
            )
            count_30d = count_result.scalar() or 0

            if quality.access_count_30d != count_30d:
                quality.access_count_30d = count_30d
                stats["updated"] += 1

        await session.commit()

    logger.info(f"Updated rolling access counts: {stats['updated']} records")
    return stats


async def recalculate_quality_scores() -> dict:
    """Recalculate quality scores based on decay and feedback.

    This reads quality scores from Graphiti (source of truth) and applies decay.
    """
    return await recalculate_quality_scores_graphiti()


async def recalculate_quality_scores_graphiti() -> dict:
    """Recalculate quality scores in Graphiti based on decay and feedback.

    Graphiti is the source of truth for quality scores. This function:
    1. Reads all chunk metadata from Graphiti
    2. Calculates decay based on access patterns
    3. Reduces decay for chunks with positive feedback
    4. Updates scores in Graphiti
    """
    stats = {"recalculated": 0, "decayed": 0}

    try:
        from knowledge_base.graph.graphiti_builder import get_graphiti_builder
        from knowledge_base.graph.graphiti_retriever import get_graphiti_retriever

        builder = get_graphiti_builder()
        retriever = get_graphiti_retriever()

        # Get all chunks from Graphiti
        all_episodes = await retriever.get_all_episodes(limit=10000)

        if not all_episodes:
            logger.info("No chunks found in Graphiti for quality recalculation")
            return stats

        chunk_ids = [ep.get("chunk_id") for ep in all_episodes if ep.get("chunk_id")]

        # Get recent helpful feedback counts from SQLite/DuckDB
        async with async_session_maker() as session:
            feedback_counts = await get_helpful_feedback_counts(session, chunk_ids)

        for episode in all_episodes:
            chunk_id = episode.get("chunk_id")
            if not chunk_id:
                continue

            metadata = episode.get("metadata", {})
            current_score = metadata.get("quality_score", 100.0)
            access_count = metadata.get("access_count", 0)

            # Calculate decay based on access patterns
            decay = calculate_decay_from_access(access_count)

            # Reduce decay for chunks with positive feedback
            helpful_count = feedback_counts.get(chunk_id, 0)
            decay_reduction = min(helpful_count * 0.3, 1.0)
            decay = max(decay - decay_reduction, 0)

            # Apply decay (minimum 0.1 per day to prevent stagnation)
            if decay > 0:
                new_score = max(current_score - decay, 0)
                if new_score < current_score:
                    await builder.update_chunk_quality(chunk_id, new_score)
                    stats["decayed"] += 1

            stats["recalculated"] += 1

        logger.info(
            f"Recalculated quality scores in Graphiti: {stats['recalculated']} total, "
            f"{stats['decayed']} decayed"
        )

    except Exception as e:
        logger.error(f"Failed to recalculate quality scores in Graphiti: {e}")

    return stats


def calculate_decay_from_access(access_count: int) -> float:
    """Calculate daily decay rate based on access count.

    Higher access = slower decay, encouraging frequently-used content.
    """
    base_decay = 2.0 / 30.0  # Base: 2 points/month = ~0.067/day

    if access_count >= 50:  # High usage
        return base_decay * 0.25  # 0.5 points/month
    elif access_count >= 20:  # Medium-high usage
        return base_decay * 0.5  # 1 point/month
    elif access_count >= 5:  # Medium usage
        return base_decay * 0.75  # 1.5 points/month
    elif access_count >= 1:  # Low usage
        return base_decay * 1.0  # 2 points/month
    else:  # No recent usage
        return base_decay * 1.5  # 3 points/month (accelerated decay)


async def get_helpful_feedback_counts(
    session: AsyncSession,
    chunk_ids: list[str],
    days: int = 90,
) -> dict[str, int]:
    """Get count of helpful feedback for multiple chunks."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    result = await session.execute(
        select(UserFeedback.chunk_id, func.count(UserFeedback.id))
        .where(UserFeedback.chunk_id.in_(chunk_ids))
        .where(UserFeedback.feedback_type == "helpful")
        .where(UserFeedback.created_at >= cutoff)
        .group_by(UserFeedback.chunk_id)
    )

    return {row[0]: row[1] for row in result.fetchall()}


async def cleanup_old_access_logs(days: int = 90) -> dict:
    """Remove access logs older than specified days."""
    stats = {"deleted": 0}
    cutoff = datetime.utcnow() - timedelta(days=days)

    async with async_session_maker() as session:
        result = await session.execute(
            select(ChunkAccessLog).where(ChunkAccessLog.accessed_at < cutoff)
        )
        old_logs = result.scalars().all()

        for log in old_logs:
            await session.delete(log)
            stats["deleted"] += 1

        await session.commit()

    logger.info(f"Cleaned up access logs: {stats['deleted']} deleted")
    return stats
