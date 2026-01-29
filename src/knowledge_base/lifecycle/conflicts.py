"""AI-assisted conflict detection and resolution for knowledge content.

Chunk data is retrieved from Graphiti (source of truth).
ContentConflict records are stored in SQLite/DuckDB for workflow tracking.
"""

import logging
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select

from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker
# ContentConflict is a workflow model kept in database
from knowledge_base.db.models import ContentConflict

from .archival import deprecate_chunk

logger = logging.getLogger(__name__)


async def report_conflict(
    chunk_a_id: str,
    chunk_b_id: str,
    conflict_type: Literal["contradiction", "outdated_duplicate", "ambiguous"],
    description: str,
    detected_by: Literal["user", "ai"] = "user",
    similarity_score: float | None = None,
    confidence_score: float | None = None,
    ai_explanation: str | None = None,
) -> ContentConflict | None:
    """Report a conflict between two chunks."""
    async with async_session_maker() as session:
        # Check if conflict already exists (in either direction)
        existing = await session.execute(
            select(ContentConflict).where(
                or_(
                    and_(
                        ContentConflict.chunk_a_id == chunk_a_id,
                        ContentConflict.chunk_b_id == chunk_b_id,
                    ),
                    and_(
                        ContentConflict.chunk_a_id == chunk_b_id,
                        ContentConflict.chunk_b_id == chunk_a_id,
                    ),
                )
            )
        )
        if existing.scalar_one_or_none():
            logger.debug(f"Conflict already exists: {chunk_a_id} <-> {chunk_b_id}")
            return None

        conflict = ContentConflict(
            chunk_a_id=chunk_a_id,
            chunk_b_id=chunk_b_id,
            conflict_type=conflict_type,
            description=description,
            detected_by=detected_by,
            similarity_score=similarity_score,
            confidence_score=confidence_score,
            ai_explanation=ai_explanation,
        )
        session.add(conflict)
        await session.commit()
        await session.refresh(conflict)

        logger.info(
            f"Conflict reported: {chunk_a_id} <-> {chunk_b_id}, "
            f"type={conflict_type}, by={detected_by}"
        )
        return conflict


async def resolve_conflict(
    conflict_id: int,
    resolution: Literal["keep_a", "keep_b", "merge", "archive_both"],
    resolved_by_slack_id: str,
) -> ContentConflict | None:
    """Resolve a content conflict."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(ContentConflict).where(ContentConflict.id == conflict_id)
        )
        conflict = result.scalar_one_or_none()

        if not conflict:
            return None

        winner = None

        if resolution == "keep_a":
            await deprecate_chunk(
                conflict.chunk_b_id,
                f"Conflict #{conflict_id}: superseded by {conflict.chunk_a_id}",
            )
            winner = conflict.chunk_a_id

        elif resolution == "keep_b":
            await deprecate_chunk(
                conflict.chunk_a_id,
                f"Conflict #{conflict_id}: superseded by {conflict.chunk_b_id}",
            )
            winner = conflict.chunk_b_id

        elif resolution == "archive_both":
            await deprecate_chunk(
                conflict.chunk_a_id,
                f"Conflict #{conflict_id}: both chunks archived",
            )
            await deprecate_chunk(
                conflict.chunk_b_id,
                f"Conflict #{conflict_id}: both chunks archived",
            )
            winner = None

        elif resolution == "merge":
            # Merge doesn't deprecate either, just marks as resolved
            winner = None

        conflict.status = "resolved"
        conflict.resolved_at = datetime.utcnow()
        conflict.resolved_by = resolved_by_slack_id
        conflict.resolution = resolution
        conflict.winner_chunk_id = winner

        await session.commit()
        await session.refresh(conflict)

        logger.info(
            f"Conflict resolved: id={conflict_id}, resolution={resolution}, "
            f"winner={winner}, by={resolved_by_slack_id}"
        )
        return conflict


async def dismiss_conflict(
    conflict_id: int,
    dismissed_by_slack_id: str,
) -> ContentConflict | None:
    """Dismiss a conflict as not actually conflicting."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(ContentConflict).where(ContentConflict.id == conflict_id)
        )
        conflict = result.scalar_one_or_none()

        if conflict:
            conflict.status = "dismissed"
            conflict.resolved_at = datetime.utcnow()
            conflict.resolved_by = dismissed_by_slack_id
            await session.commit()
            await session.refresh(conflict)

            logger.info(f"Conflict dismissed: id={conflict_id}")

        return conflict


async def get_open_conflicts(limit: int = 50) -> list[ContentConflict]:
    """Get all open conflicts awaiting resolution."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(ContentConflict)
            .where(ContentConflict.status == "open")
            .order_by(ContentConflict.detected_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


async def get_conflict_with_chunks(conflict_id: int) -> dict | None:
    """Get a conflict with full chunk content for comparison.

    Retrieves chunk data from Graphiti (source of truth).
    """
    async with async_session_maker() as session:
        # Get conflict from database
        result = await session.execute(
            select(ContentConflict).where(ContentConflict.id == conflict_id)
        )
        conflict = result.scalar_one_or_none()
        if not conflict:
            return None

    # Get chunk data from Graphiti (source of truth)
    from knowledge_base.graph.graphiti_builder import get_graphiti_builder

    builder = get_graphiti_builder()
    chunk_ids = [conflict.chunk_a_id, conflict.chunk_b_id]

    # Build lookup map from Graphiti results
    chunk_map = {}
    for chunk_id in chunk_ids:
        episode = await builder.get_chunk_episode(chunk_id)
        if episode:
            chunk_map[chunk_id] = {
                "content": episode.get("content"),
                "page_title": episode.get("metadata", {}).get("page_title"),
            }

    return {
        "conflict": conflict,
        "chunk_a": {
            "id": conflict.chunk_a_id,
            "content": chunk_map.get(conflict.chunk_a_id, {}).get("content"),
            "page_title": chunk_map.get(conflict.chunk_a_id, {}).get("page_title"),
        },
        "chunk_b": {
            "id": conflict.chunk_b_id,
            "content": chunk_map.get(conflict.chunk_b_id, {}).get("content"),
            "page_title": chunk_map.get(conflict.chunk_b_id, {}).get("page_title"),
        },
    }


async def detect_conflicts_for_chunk(
    chunk_id: str,
    similar_chunks: list[tuple[str, float]],  # List of (chunk_id, similarity_score)
    llm_check_func=None,  # Optional LLM function for contradiction detection
) -> list[ContentConflict]:
    """
    Detect conflicts for a chunk against similar chunks.

    Retrieves chunk data from Graphiti (source of truth).

    Args:
        chunk_id: The chunk to check
        similar_chunks: List of (chunk_id, similarity_score) tuples from embedding search
        llm_check_func: Optional async function(chunk_a_content, chunk_b_content) -> dict
                        Returns {"is_contradiction": bool, "confidence": float, "explanation": str}
    """
    from knowledge_base.graph.graphiti_builder import get_graphiti_builder

    conflicts = []

    # Get all needed chunks from Graphiti
    all_chunk_ids = [chunk_id] + [cid for cid, _ in similar_chunks]
    builder = get_graphiti_builder()

    # Build lookup map
    chunk_map = {}
    for cid in all_chunk_ids:
        episode = await builder.get_chunk_episode(cid)
        if episode:
            chunk_map[cid] = {
                "content": episode.get("content", ""),
                "page_id": episode.get("metadata", {}).get("page_id", ""),
            }

    source_chunk = chunk_map.get(chunk_id)
    if not source_chunk or not source_chunk.get("content"):
        return conflicts

    for similar_chunk_id, similarity in similar_chunks:
        if similarity < settings.CONFLICT_SIMILARITY_THRESHOLD:
            continue

        similar_chunk = chunk_map.get(similar_chunk_id)
        if not similar_chunk or not similar_chunk.get("content"):
            continue

        # Skip if same page
        if source_chunk.get("page_id") == similar_chunk.get("page_id"):
            continue

        # If LLM function provided, use it to check for contradiction
        if llm_check_func:
            try:
                llm_result = await llm_check_func(
                    source_chunk["content"],
                    similar_chunk["content"],
                )
                if (
                    llm_result.get("is_contradiction")
                    and llm_result.get("confidence", 0) > settings.CONFLICT_CONFIDENCE_THRESHOLD
                ):
                    conflict = await report_conflict(
                        chunk_a_id=chunk_id,
                        chunk_b_id=similar_chunk_id,
                        conflict_type="contradiction",
                        description=llm_result.get("explanation", "AI-detected contradiction"),
                        detected_by="ai",
                        similarity_score=similarity,
                        confidence_score=llm_result.get("confidence"),
                        ai_explanation=llm_result.get("explanation"),
                    )
                    if conflict:
                        conflicts.append(conflict)
            except Exception as e:
                logger.warning(f"LLM conflict check failed: {e}")
        else:
            # Without LLM, flag high similarity as potential duplicate
            conflict = await report_conflict(
                chunk_a_id=chunk_id,
                chunk_b_id=similar_chunk_id,
                conflict_type="outdated_duplicate",
                description=f"High similarity ({similarity:.2f}) detected between chunks",
                detected_by="ai",
                similarity_score=similarity,
            )
            if conflict:
                conflicts.append(conflict)

    return conflicts


async def run_conflict_detection_batch(
    days: int = 7,
    llm_check_func=None,
    find_similar_func=None,  # async function(chunk_id) -> list[(chunk_id, similarity)]
    chunk_ids: list[str] | None = None,  # Optional pre-provided chunk IDs
) -> dict:
    """
    Scheduled job to detect conflicts across recently modified chunks.

    Chunk data is retrieved from Graphiti (source of truth).

    Args:
        days: Check chunks created/modified in last N days
        llm_check_func: Optional LLM function for contradiction detection
        find_similar_func: Function to find similar chunks via embeddings
        chunk_ids: Optional list of chunk IDs to check (overrides days filter)
    """
    stats = {"scanned": 0, "conflicts_found": 0}

    if not find_similar_func:
        logger.warning("No similarity function provided, skipping conflict detection")
        return stats

    # If chunk_ids not provided, query Graphiti for recent chunks
    if chunk_ids is None:
        from knowledge_base.graph.graphiti_retriever import get_graphiti_retriever

        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        # Get recent chunks from Graphiti
        retriever = get_graphiti_retriever()
        recent_episodes = await retriever.get_recent_episodes(days=days, limit=10000)

        chunk_ids = [ep.get("chunk_id") for ep in recent_episodes if ep.get("chunk_id")]

        logger.info(f"Found {len(chunk_ids)} chunks created since {cutoff_iso}")

    for chunk_id in chunk_ids:
        try:
            similar_chunks = await find_similar_func(chunk_id)
            conflicts = await detect_conflicts_for_chunk(
                chunk_id,
                similar_chunks,
                llm_check_func,
            )
            stats["conflicts_found"] += len(conflicts)
        except Exception as e:
            logger.warning(f"Error checking conflicts for {chunk_id}: {e}")

        stats["scanned"] += 1

    logger.info(
        f"Conflict detection batch complete: scanned={stats['scanned']}, "
        f"found={stats['conflicts_found']}"
    )
    return stats


async def get_conflict_stats() -> dict:
    """Get statistics about conflicts."""
    async with async_session_maker() as session:
        # Count by status
        status_result = await session.execute(
            select(
                ContentConflict.status,
                func.count(ContentConflict.id),
            ).group_by(ContentConflict.status)
        )
        by_status = {row[0]: row[1] for row in status_result.fetchall()}

        # Count by type
        type_result = await session.execute(
            select(
                ContentConflict.conflict_type,
                func.count(ContentConflict.id),
            ).group_by(ContentConflict.conflict_type)
        )
        by_type = {row[0]: row[1] for row in type_result.fetchall()}

        # Total
        total_result = await session.execute(
            select(func.count(ContentConflict.id))
        )
        total = total_result.scalar() or 0

        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
        }
