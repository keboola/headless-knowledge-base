"""Index chunks into Graphiti as episodes.

This module replaces VectorIndexer for chunk storage, making Graphiti
the single source of truth for all knowledge data.
"""

import logging
from typing import Any, Callable, TYPE_CHECKING

from knowledge_base.config import settings
from knowledge_base.graph.graphiti_builder import get_graphiti_builder

if TYPE_CHECKING:
    from knowledge_base.vectorstore.indexer import ChunkData

logger = logging.getLogger(__name__)


class GraphitiIndexer:
    """Indexes chunks into Graphiti as episodes.

    Replaces VectorIndexer for chunk storage. Accepts ChunkData objects
    and stores them as Graphiti episodes with full metadata.
    """

    def __init__(self, batch_size: int | None = None):
        """Initialize the Graphiti indexer.

        Args:
            batch_size: Number of chunks to process before logging progress
        """
        self.batch_size = batch_size or settings.INDEX_BATCH_SIZE
        self._builder = None

    def _get_builder(self):
        """Get GraphitiBuilder lazily."""
        if self._builder is None:
            self._builder = get_graphiti_builder()
        return self._builder

    async def index_chunks_direct(
        self,
        chunks: list["ChunkData | dict[str, Any]"],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Index chunks directly to Graphiti.

        Args:
            chunks: List of ChunkData objects or dicts with chunk information
            progress_callback: Optional callback(indexed, total) for progress updates

        Returns:
            Number of successfully indexed chunks
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            logger.warning("Graphiti disabled, skipping indexing")
            return 0

        builder = self._get_builder()
        total = len(chunks)
        indexed = 0
        errors = 0

        logger.info(f"Indexing {total} chunks to Graphiti...")

        for i, chunk in enumerate(chunks):
            try:
                result = await builder.add_chunk_episode(chunk)
                if result.get("success"):
                    indexed += 1
                else:
                    errors += 1
                    if result.get("reason") != "empty_content":
                        logger.warning(f"Failed to index chunk: {result}")

            except Exception as e:
                errors += 1
                chunk_id = chunk.chunk_id if hasattr(chunk, 'chunk_id') else chunk.get('chunk_id', 'unknown')
                logger.error(f"Error indexing chunk {chunk_id}: {e}")

            # Progress callback
            if progress_callback:
                progress_callback(i + 1, total)

            # Log batch progress
            if (i + 1) % self.batch_size == 0:
                logger.info(f"Indexed {i + 1}/{total} chunks ({indexed} success, {errors} errors)")

        logger.info(f"Completed indexing: {indexed}/{total} chunks indexed, {errors} errors")
        return indexed

    async def index_single_chunk(
        self,
        chunk: "ChunkData | dict[str, Any]",
    ) -> bool:
        """Index a single chunk to Graphiti.

        Args:
            chunk: ChunkData object or dict with chunk information

        Returns:
            True if successful, False otherwise
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            logger.warning("Graphiti disabled, skipping single chunk indexing")
            return False

        builder = self._get_builder()

        try:
            result = await builder.add_chunk_episode(chunk)
            return result.get("success", False)
        except Exception as e:
            chunk_id = chunk.chunk_id if hasattr(chunk, 'chunk_id') else chunk.get('chunk_id', 'unknown')
            logger.error(f"Error indexing single chunk {chunk_id}: {e}")
            return False

    async def delete_chunks(self, chunk_ids: list[str]) -> int:
        """Delete chunks from Graphiti by chunk_id.

        Args:
            chunk_ids: List of chunk IDs to delete

        Returns:
            Number of successfully deleted chunks
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            return 0

        builder = self._get_builder()
        deleted = 0

        for chunk_id in chunk_ids:
            try:
                if await builder.delete_chunk_episode(chunk_id):
                    deleted += 1
            except Exception as e:
                logger.error(f"Error deleting chunk {chunk_id}: {e}")

        logger.info(f"Deleted {deleted}/{len(chunk_ids)} chunks from Graphiti")
        return deleted

    async def update_chunk_quality(
        self,
        chunk_id: str,
        new_score: float,
        increment_feedback_count: bool = True,
    ) -> bool:
        """Update quality score for a chunk.

        Args:
            chunk_id: The chunk ID to update
            new_score: New quality score (0-100)
            increment_feedback_count: Whether to increment feedback_count

        Returns:
            True if successful, False otherwise
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            return False

        builder = self._get_builder()
        return await builder.update_chunk_quality(
            chunk_id, new_score, increment_feedback_count
        )

    async def get_chunk_count(self) -> int:
        """Get total number of indexed chunks.

        Returns:
            Number of chunks in Graphiti (approximate)
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            return 0

        # Note: This requires querying Graphiti stats
        # Placeholder implementation
        builder = self._get_builder()
        stats = await builder.get_stats()
        return stats.get("episode_count", 0)


# Factory function
_default_indexer: GraphitiIndexer | None = None


def get_graphiti_indexer() -> GraphitiIndexer:
    """Get the default GraphitiIndexer instance.

    Returns:
        GraphitiIndexer configured from settings
    """
    global _default_indexer
    if _default_indexer is None:
        _default_indexer = GraphitiIndexer()
    return _default_indexer
