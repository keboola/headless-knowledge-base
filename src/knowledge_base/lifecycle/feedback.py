"""User feedback collection and processing for content chunks.

ChromaDB is the SOURCE OF TRUTH for quality scores per docs/ARCHITECTURE.md.
UserFeedback records are stored in SQLite/DuckDB for analytics and retraining.
"""

import logging
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker
from knowledge_base.db.models import UserFeedback
from knowledge_base.vectorstore.client import ChromaClient

logger = logging.getLogger(__name__)

# Singleton ChromaDB client for feedback operations
_chroma_client: ChromaClient | None = None


def get_chroma_client() -> ChromaClient:
    """Get or create a ChromaDB client instance."""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = ChromaClient()
    return _chroma_client

FeedbackType = Literal["helpful", "outdated", "incorrect", "confusing"]


def get_feedback_score_impact(feedback_type: FeedbackType) -> int:
    """Get the score impact for a feedback type."""
    impacts = {
        "helpful": settings.FEEDBACK_SCORE_HELPFUL,
        "outdated": settings.FEEDBACK_SCORE_OUTDATED,
        "incorrect": settings.FEEDBACK_SCORE_INCORRECT,
        "confusing": settings.FEEDBACK_SCORE_CONFUSING,
    }
    return impacts.get(feedback_type, 0)


async def submit_feedback(
    chunk_id: str,
    slack_user_id: str,
    slack_username: str,
    feedback_type: FeedbackType,
    slack_channel_id: str | None = None,
    comment: str | None = None,
    suggested_correction: str | None = None,
    query_context: str | None = None,
    conversation_thread_ts: str | None = None,
) -> UserFeedback:
    """
    Submit user feedback on a content chunk.

    Quality score is updated in ChromaDB (source of truth) immediately.
    Feedback record is stored in SQLite/DuckDB for analytics and retraining.
    """
    # 1. Update quality score in ChromaDB FIRST (source of truth)
    score_impact = get_feedback_score_impact(feedback_type)
    await apply_feedback_to_quality_chromadb(chunk_id, score_impact)

    # 2. Store feedback record in SQLite/DuckDB (for analytics/retraining)
    async with async_session_maker() as session:
        feedback = UserFeedback(
            chunk_id=chunk_id,
            slack_user_id=slack_user_id,
            slack_username=slack_username,
            slack_channel_id=slack_channel_id,
            feedback_type=feedback_type,
            comment=comment,
            suggested_correction=suggested_correction,
            query_context=query_context,
            conversation_thread_ts=conversation_thread_ts,
        )
        session.add(feedback)
        await session.commit()
        await session.refresh(feedback)

        logger.info(
            f"Feedback submitted: chunk={chunk_id}, type={feedback_type}, "
            f"user={slack_username}, impact={score_impact}"
        )
        return feedback


async def apply_feedback_to_quality_chromadb(
    chunk_id: str,
    score_impact: int,
) -> None:
    """Apply feedback score impact directly to ChromaDB (source of truth).

    ChromaDB stores the authoritative quality score. No SQLite sync needed.
    """
    chroma = get_chroma_client()

    # Get current quality score from ChromaDB
    current_score = await chroma.get_quality_score(chunk_id)

    if current_score is not None:
        # Apply impact (positive feedback caps at 100, negative at 0)
        new_score = current_score + score_impact
        if score_impact > 0:
            new_score = min(new_score, 100.0)  # Cap at max score
        new_score = max(new_score, 0.0)  # Don't go below 0
    else:
        # Chunk not found in ChromaDB - this shouldn't happen
        # but handle gracefully
        logger.warning(f"Chunk {chunk_id} not found in ChromaDB for feedback")
        new_score = max(100.0 + score_impact, 0.0)

    # Update quality score in ChromaDB
    await chroma.update_quality_score(
        chunk_id=chunk_id,
        new_score=new_score,
        increment_feedback_count=True,
    )

    logger.debug(f"Updated quality score in ChromaDB: {chunk_id} -> {new_score}")


async def apply_feedback_to_quality(
    session: AsyncSession,
    chunk_id: str,
    score_impact: int,
) -> None:
    """Apply feedback score impact to chunk quality.

    DEPRECATED: Use apply_feedback_to_quality_chromadb() instead.
    This function is kept for backward compatibility during migration.
    """
    # Delegate to ChromaDB-first implementation
    await apply_feedback_to_quality_chromadb(chunk_id, score_impact)


async def get_feedback_for_chunk(chunk_id: str) -> list[UserFeedback]:
    """Get all feedback for a specific chunk."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserFeedback)
            .where(UserFeedback.chunk_id == chunk_id)
            .order_by(UserFeedback.created_at.desc())
        )
        return list(result.scalars().all())


async def get_unreviewed_feedback(limit: int = 50) -> list[UserFeedback]:
    """Get feedback that needs admin review."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserFeedback)
            .where(UserFeedback.reviewed == False)  # noqa: E712
            .order_by(UserFeedback.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


async def get_high_impact_feedback(limit: int = 50) -> list[UserFeedback]:
    """Get feedback with high negative impact (outdated, incorrect)."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserFeedback)
            .where(UserFeedback.feedback_type.in_(["outdated", "incorrect"]))
            .where(UserFeedback.reviewed == False)  # noqa: E712
            .order_by(UserFeedback.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


async def review_feedback(
    feedback_id: int,
    review_action: Literal["accepted", "rejected", "deferred"],
    reviewed_by: str,
) -> UserFeedback | None:
    """Mark feedback as reviewed with action taken."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(UserFeedback).where(UserFeedback.id == feedback_id)
        )
        feedback = result.scalar_one_or_none()

        if feedback:
            feedback.reviewed = True
            feedback.review_action = review_action
            feedback.reviewed_by = reviewed_by
            feedback.reviewed_at = datetime.utcnow()
            await session.commit()
            await session.refresh(feedback)

            logger.info(
                f"Feedback reviewed: id={feedback_id}, action={review_action}, "
                f"by={reviewed_by}"
            )

        return feedback


async def get_feedback_stats() -> dict:
    """Get statistics about feedback."""
    async with async_session_maker() as session:
        # Total counts by type
        result = await session.execute(
            select(
                UserFeedback.feedback_type,
                func.count(UserFeedback.id),
            ).group_by(UserFeedback.feedback_type)
        )
        by_type = {row[0]: row[1] for row in result.fetchall()}

        # Unreviewed count
        unreviewed_result = await session.execute(
            select(func.count(UserFeedback.id)).where(
                UserFeedback.reviewed == False  # noqa: E712
            )
        )
        unreviewed = unreviewed_result.scalar() or 0

        # Total count
        total_result = await session.execute(
            select(func.count(UserFeedback.id))
        )
        total = total_result.scalar() or 0

        return {
            "total": total,
            "unreviewed": unreviewed,
            "by_type": by_type,
        }
