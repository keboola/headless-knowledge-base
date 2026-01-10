"""Sync quality scores and governance metadata to ChromaDB.

DEPRECATED: This module is deprecated as of the ChromaDB source-of-truth migration.
See docs/adr/0005-chromadb-source-of-truth.md

ChromaDB is now the source of truth for quality scores and governance metadata.
Quality updates should go directly to ChromaDB using:
- knowledge_base.lifecycle.feedback.apply_feedback_to_quality_chromadb()
- knowledge_base.vectorstore.client.ChromaClient.update_quality_score()

This module is kept for backward compatibility during migration but will be removed.
"""

import logging
from typing import Any

from knowledge_base.vectorstore.client import ChromaClient

logger = logging.getLogger(__name__)

# Singleton client instance (reused across calls)
_chroma_client: ChromaClient | None = None


def get_chroma_client() -> ChromaClient:
    """Get or create a ChromaDB client instance."""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = ChromaClient()
    return _chroma_client


async def sync_quality_score_to_chromadb(
    chunk_id: str,
    quality_score: float,
    feedback_count: int | None = None,
) -> bool:
    """Update the quality_score in ChromaDB metadata for a chunk.

    Args:
        chunk_id: The chunk ID to update
        quality_score: New quality score (0-100)
        feedback_count: Optional feedback count to update

    Returns:
        True if update succeeded, False otherwise
    """
    try:
        chroma = get_chroma_client()

        metadata: dict[str, Any] = {
            "quality_score": quality_score,
        }
        if feedback_count is not None:
            metadata["feedback_count"] = feedback_count

        await chroma.update_metadata(
            ids=[chunk_id],
            metadatas=[metadata],
        )

        logger.info(
            f"Synced quality_score={quality_score} to ChromaDB for chunk {chunk_id}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to sync quality score to ChromaDB: {e}")
        return False


async def sync_governance_to_chromadb(
    chunk_id: str,
    owner: str | None = None,
    reviewed_by: str | None = None,
    reviewed_at: str | None = None,
    classification: str | None = None,
) -> bool:
    """Update governance metadata in ChromaDB for a chunk.

    Args:
        chunk_id: The chunk ID to update
        owner: Document owner
        reviewed_by: Who reviewed the document
        reviewed_at: When it was reviewed (ISO format string)
        classification: Classification level (public, internal, confidential)

    Returns:
        True if update succeeded, False otherwise
    """
    try:
        chroma = get_chroma_client()

        metadata: dict[str, Any] = {}
        if owner is not None:
            metadata["owner"] = owner
        if reviewed_by is not None:
            metadata["reviewed_by"] = reviewed_by
        if reviewed_at is not None:
            metadata["reviewed_at"] = reviewed_at
        if classification is not None:
            metadata["classification"] = classification

        if not metadata:
            return True  # Nothing to update

        await chroma.update_metadata(
            ids=[chunk_id],
            metadatas=[metadata],
        )

        logger.info(f"Synced governance metadata to ChromaDB for chunk {chunk_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to sync governance to ChromaDB: {e}")
        return False


async def batch_sync_quality_scores(
    updates: list[tuple[str, float]],
) -> int:
    """Batch update quality scores in ChromaDB.

    Args:
        updates: List of (chunk_id, quality_score) tuples

    Returns:
        Number of successful updates
    """
    if not updates:
        return 0

    try:
        chroma = get_chroma_client()

        ids = [chunk_id for chunk_id, _ in updates]
        metadatas = [{"quality_score": score} for _, score in updates]

        await chroma.update_metadata(ids=ids, metadatas=metadatas)

        logger.info(f"Batch synced {len(updates)} quality scores to ChromaDB")
        return len(updates)

    except Exception as e:
        logger.error(f"Failed to batch sync quality scores: {e}")
        return 0


async def get_quality_score_from_chromadb(chunk_id: str) -> float | None:
    """Get quality score from ChromaDB metadata.

    Args:
        chunk_id: The chunk ID to query

    Returns:
        Quality score if found, None otherwise
    """
    try:
        chroma = get_chroma_client()
        result = await chroma.get(ids=[chunk_id])

        if result and result.get("metadatas") and result["metadatas"]:
            metadata = result["metadatas"][0]
            return metadata.get("quality_score")

        return None

    except Exception as e:
        logger.warning(f"Failed to get quality score from ChromaDB: {e}")
        return None


async def get_quality_scores_from_chromadb(
    chunk_ids: list[str],
) -> dict[str, float]:
    """Get quality scores for multiple chunks from ChromaDB.

    Args:
        chunk_ids: List of chunk IDs to query

    Returns:
        Dict mapping chunk_id to quality_score
    """
    if not chunk_ids:
        return {}

    try:
        chroma = get_chroma_client()
        result = await chroma.get(ids=chunk_ids)

        scores = {}
        if result and result.get("ids") and result.get("metadatas"):
            for chunk_id, metadata in zip(result["ids"], result["metadatas"]):
                if metadata and "quality_score" in metadata:
                    scores[chunk_id] = metadata["quality_score"]

        return scores

    except Exception as e:
        logger.warning(f"Failed to get quality scores from ChromaDB: {e}")
        return {}
