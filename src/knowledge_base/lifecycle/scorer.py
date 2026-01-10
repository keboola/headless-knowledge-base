"""Quality scoring for search ranking integration (Phase 11).

Calculates normalized quality scores (0.0-1.0) from feedback, usage,
and freshness signals to boost or demote search results.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker
from knowledge_base.db.models import (
    BehavioralSignal,
    Chunk,
    ChunkAccessLog,
    ChunkQuality,
    RawPage,
    UserFeedback,
)

logger = logging.getLogger(__name__)


# Score weights (must sum to 1.0)
SCORE_WEIGHTS = {
    "feedback": 0.35,    # Explicit feedback (helpful/outdated/incorrect)
    "behavior": 0.25,    # Behavioral signals (Phase 10.5)
    "relevance": 0.25,   # Usage frequency (how often shown)
    "freshness": 0.15,   # Document age
}


def calc_feedback_score(positive_count: int, negative_count: int) -> float:
    """Calculate feedback score from counts.

    Returns 0.0-1.0 where:
    - 0.5 = neutral (no feedback or balanced)
    - > 0.5 = positive feedback dominates
    - < 0.5 = negative feedback dominates
    """
    total = positive_count + negative_count
    if total == 0:
        return 0.5  # Neutral default

    # Ratio of positive to total
    positive_ratio = positive_count / total

    # Apply smoothing for low counts
    if total < 5:
        # Move toward neutral for low sample size
        smoothing = (5 - total) / 5 * 0.5
        return positive_ratio * (1 - smoothing) + 0.5 * smoothing

    return positive_ratio


def calc_relevance_score(access_count_30d: int, total_access_count: int) -> float:
    """Calculate relevance score from usage patterns.

    Returns 0.0-1.0 based on how often the chunk is accessed.
    Uses logarithmic scaling to prevent high-traffic docs from dominating.
    """
    import math

    if total_access_count == 0:
        return 0.5  # Neutral for unused

    # Recent activity matters more
    if access_count_30d > 0:
        # Log scale: 1 access = ~0.5, 10 = ~0.7, 50+ = ~0.9
        log_score = min(1.0, 0.5 + math.log10(1 + access_count_30d) * 0.2)
    else:
        # No recent activity, but has history
        log_score = 0.3 + min(0.2, math.log10(1 + total_access_count) * 0.05)

    return log_score


def calc_freshness_score(updated_at: datetime | None) -> float:
    """Calculate freshness score based on document age.

    Returns 0.0-1.0 where fresher documents score higher.
    """
    if updated_at is None:
        return 0.5  # Unknown age = neutral

    # Handle timezone-aware datetimes
    now = datetime.utcnow()
    if updated_at.tzinfo is not None:
        from datetime import timezone
        now = datetime.now(timezone.utc)

    age_days = (now - updated_at).days

    if age_days < 30:
        return 1.0
    elif age_days < 90:
        return 0.9
    elif age_days < 180:
        return 0.75
    elif age_days < 365:
        return 0.6
    elif age_days < 730:  # 2 years
        return 0.4
    else:
        return 0.2


def calc_behavior_score(signals: list[tuple[str, float]]) -> float:
    """Calculate behavior score from behavioral signals.

    Args:
        signals: List of (signal_type, signal_value) tuples

    Returns:
        0.0-1.0 score where higher is better
    """
    if not signals:
        return 0.5  # Neutral default

    # Average the signal values
    total_value = sum(value for _, value in signals)
    avg_value = total_value / len(signals)

    # Signal values are in range [-1, +1], normalize to [0, 1]
    normalized = (avg_value + 1) / 2

    # Apply smoothing for low sample size
    if len(signals) < 3:
        smoothing = (3 - len(signals)) / 3 * 0.5
        return normalized * (1 - smoothing) + 0.5 * smoothing

    return min(max(normalized, 0.0), 1.0)


async def get_chunk_feedback_counts(
    session: AsyncSession, chunk_id: str
) -> tuple[int, int]:
    """Get positive and negative feedback counts for a chunk."""
    positive_types = ["helpful"]
    negative_types = ["outdated", "incorrect", "confusing"]

    # Count positive
    pos_result = await session.execute(
        select(func.count(UserFeedback.id))
        .where(UserFeedback.chunk_id == chunk_id)
        .where(UserFeedback.feedback_type.in_(positive_types))
    )
    positive = pos_result.scalar() or 0

    # Count negative
    neg_result = await session.execute(
        select(func.count(UserFeedback.id))
        .where(UserFeedback.chunk_id == chunk_id)
        .where(UserFeedback.feedback_type.in_(negative_types))
    )
    negative = neg_result.scalar() or 0

    return positive, negative


async def calculate_chunk_quality_score(chunk_id: str) -> float:
    """Calculate the normalized quality score (0.0-1.0) for a chunk.

    Combines feedback, relevance, and freshness signals.
    """
    async with async_session_maker() as session:
        # Get ChunkQuality record
        result = await session.execute(
            select(ChunkQuality).where(ChunkQuality.chunk_id == chunk_id)
        )
        quality = result.scalar_one_or_none()

        # Get page updated_at for freshness
        chunk_result = await session.execute(
            select(Chunk).where(Chunk.chunk_id == chunk_id)
        )
        chunk = chunk_result.scalar_one_or_none()

        page_updated_at = None
        if chunk:
            page_result = await session.execute(
                select(RawPage).where(RawPage.page_id == chunk.page_id)
            )
            page = page_result.scalar_one_or_none()
            if page:
                page_updated_at = page.updated_at

        # Calculate component scores
        positive, negative = await get_chunk_feedback_counts(session, chunk_id)
        feedback_score = calc_feedback_score(positive, negative)

        access_30d = quality.access_count_30d if quality else 0
        total_access = quality.access_count if quality else 0
        relevance_score = calc_relevance_score(access_30d, total_access)

        freshness_score = calc_freshness_score(page_updated_at)

        # Weighted average
        normalized_score = (
            SCORE_WEIGHTS["feedback"] * feedback_score
            + SCORE_WEIGHTS["relevance"] * relevance_score
            + SCORE_WEIGHTS["freshness"] * freshness_score
        )

        return min(max(normalized_score, 0.0), 1.0)


async def get_quality_scores_for_chunks(chunk_ids: list[str]) -> dict[str, float]:
    """Get normalized quality scores for multiple chunks efficiently.

    Returns a dict mapping chunk_id -> normalized_score (0.0-1.0).
    Chunks without quality records get a neutral score of 0.5.
    """
    if not chunk_ids:
        return {}

    scores = {}

    async with async_session_maker() as session:
        # Batch fetch quality records
        result = await session.execute(
            select(ChunkQuality).where(ChunkQuality.chunk_id.in_(chunk_ids))
        )
        quality_records = {q.chunk_id: q for q in result.scalars().all()}

        # Get feedback counts in batch
        feedback_result = await session.execute(
            select(
                UserFeedback.chunk_id,
                UserFeedback.feedback_type,
                func.count(UserFeedback.id),
            )
            .where(UserFeedback.chunk_id.in_(chunk_ids))
            .group_by(UserFeedback.chunk_id, UserFeedback.feedback_type)
        )

        feedback_counts: dict[str, dict[str, int]] = {}
        for row in feedback_result.fetchall():
            chunk_id, ftype, count = row
            if chunk_id not in feedback_counts:
                feedback_counts[chunk_id] = {"positive": 0, "negative": 0}
            if ftype == "helpful":
                feedback_counts[chunk_id]["positive"] = count
            else:
                feedback_counts[chunk_id]["negative"] += count

        # Get page freshness data in batch
        chunk_result = await session.execute(
            select(Chunk.chunk_id, RawPage.updated_at)
            .join(RawPage, Chunk.page_id == RawPage.page_id)
            .where(Chunk.chunk_id.in_(chunk_ids))
        )
        freshness_data = {row[0]: row[1] for row in chunk_result.fetchall()}

        # Get behavioral signals in batch (Phase 10.5)
        behavior_signals: dict[str, list[tuple[str, float]]] = {cid: [] for cid in chunk_ids}
        try:
            # Query signals that contain any of our chunk_ids
            # Note: This is a simplification; in production you'd want better JSON querying
            signal_result = await session.execute(
                select(BehavioralSignal.chunk_ids, BehavioralSignal.signal_type, BehavioralSignal.signal_value)
            )
            for row in signal_result.fetchall():
                chunk_ids_json, signal_type, signal_value = row
                try:
                    import json
                    signal_chunk_ids = json.loads(chunk_ids_json) if chunk_ids_json else []
                    for cid in signal_chunk_ids:
                        if cid in behavior_signals:
                            behavior_signals[cid].append((signal_type, signal_value))
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception as e:
            logger.warning(f"Failed to fetch behavioral signals: {e}")

        # Calculate scores for each chunk
        for chunk_id in chunk_ids:
            quality = quality_records.get(chunk_id)

            # Feedback score
            fc = feedback_counts.get(chunk_id, {"positive": 0, "negative": 0})
            feedback_score = calc_feedback_score(fc["positive"], fc["negative"])

            # Behavior score (Phase 10.5)
            behavior_score = calc_behavior_score(behavior_signals.get(chunk_id, []))

            # Relevance score
            access_30d = quality.access_count_30d if quality else 0
            total_access = quality.access_count if quality else 0
            relevance_score = calc_relevance_score(access_30d, total_access)

            # Freshness score
            updated_at = freshness_data.get(chunk_id)
            freshness_score = calc_freshness_score(updated_at)

            # Weighted average
            score = (
                SCORE_WEIGHTS["feedback"] * feedback_score
                + SCORE_WEIGHTS["behavior"] * behavior_score
                + SCORE_WEIGHTS["relevance"] * relevance_score
                + SCORE_WEIGHTS["freshness"] * freshness_score
            )

            scores[chunk_id] = min(max(score, 0.0), 1.0)

    return scores


def apply_quality_boost(
    results: list[Any],
    quality_scores: dict[str, float],
    boost_weight: float = 0.2,
) -> list[Any]:
    """Apply quality score boosting to search results.

    Adjusts the result score based on quality:
    final_score = original_score * (1 + boost_weight * (quality - 0.5))

    This means:
    - Quality 0.5 (neutral) = no change
    - Quality 1.0 = +boost_weight boost (e.g., +20%)
    - Quality 0.0 = -boost_weight penalty (e.g., -20%)

    Args:
        results: List of search results with .chunk_id and .score attributes
        quality_scores: Dict mapping chunk_id -> quality score (0-1)
        boost_weight: How much quality affects final score (default 0.2 = 20%)

    Returns:
        Results re-sorted by boosted score
    """
    # Calculate boosted scores
    boosted_results = []
    for result in results:
        quality = quality_scores.get(result.chunk_id, 0.5)  # Default neutral
        # Quality adjustment: -0.5 to +0.5 range
        quality_adjustment = quality - 0.5
        # Apply boost
        boosted_score = result.score * (1 + boost_weight * quality_adjustment * 2)
        boosted_results.append((result, boosted_score))

    # Sort by boosted score descending
    boosted_results.sort(key=lambda x: x[1], reverse=True)

    # Update scores on results
    for result, boosted_score in boosted_results:
        result.score = boosted_score

    return [r for r, _ in boosted_results]


async def get_quality_stats() -> dict[str, Any]:
    """Get statistics about quality scores."""
    async with async_session_maker() as session:
        # Total chunks with quality records
        total_result = await session.execute(select(func.count(ChunkQuality.id)))
        total = total_result.scalar() or 0

        # Score distribution
        score_result = await session.execute(
            select(
                func.avg(ChunkQuality.quality_score),
                func.min(ChunkQuality.quality_score),
                func.max(ChunkQuality.quality_score),
            )
        )
        row = score_result.fetchone()
        avg_score, min_score, max_score = row if row else (0, 0, 0)

        # Status distribution
        status_result = await session.execute(
            select(ChunkQuality.status, func.count(ChunkQuality.id)).group_by(
                ChunkQuality.status
            )
        )
        by_status = {row[0]: row[1] for row in status_result.fetchall()}

        # Recent feedback
        cutoff = datetime.utcnow() - timedelta(days=7)
        recent_feedback = await session.execute(
            select(func.count(UserFeedback.id)).where(
                UserFeedback.created_at >= cutoff
            )
        )
        recent_count = recent_feedback.scalar() or 0

        return {
            "total_tracked": total,
            "average_score": round(avg_score, 2) if avg_score else 0,
            "min_score": round(min_score, 2) if min_score else 0,
            "max_score": round(max_score, 2) if max_score else 0,
            "by_status": by_status,
            "feedback_last_7_days": recent_count,
        }
