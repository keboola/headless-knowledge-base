"""Index chunks into Graphiti as episodes.

This module replaces VectorIndexer for chunk storage, making Graphiti
the single source of truth for all knowledge data.
"""

import asyncio
import logging
import random
import time
import uuid
from datetime import datetime
from typing import Any, Callable, TYPE_CHECKING

from knowledge_base.config import settings
from knowledge_base.graph.graphiti_builder import get_graphiti_builder

if TYPE_CHECKING:
    from knowledge_base.vectorstore.indexer import ChunkData

logger = logging.getLogger(__name__)

# Rate limit handling configuration
MAX_RETRIES = 5
BASE_DELAY = 2.0  # Base delay in seconds
MAX_DELAY = 120.0  # Maximum delay (2 minutes)
INTER_CHUNK_DELAY = 1.0  # Delay between chunks to avoid rate limits


def _is_rate_limit_error(error: Exception | str) -> bool:
    """Check if an error is a rate limit error."""
    error_str = str(error).lower()
    return any(phrase in error_str for phrase in [
        "rate limit",
        "rate_limit",
        "quota exceeded",
        "resource exhausted",
        "too many requests",
        "429",
    ])


async def _retry_with_backoff(
    coro_func: Callable,
    *args,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY,
    max_delay: float = MAX_DELAY,
    **kwargs,
) -> dict[str, Any]:
    """Retry an async function with exponential backoff.

    Specifically handles rate limit errors with longer delays.

    Args:
        coro_func: Async function to call
        *args: Positional arguments for the function
        max_retries: Maximum retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        **kwargs: Keyword arguments for the function

    Returns:
        Result from the function, or error dict if all retries fail
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            result = await coro_func(*args, **kwargs)

            # Check if result indicates a rate limit error (not an exception)
            if isinstance(result, dict) and not result.get("success"):
                error_msg = result.get("error", "")
                if _is_rate_limit_error(error_msg):
                    if attempt < max_retries:
                        # Calculate delay with exponential backoff + jitter
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        jitter = random.uniform(0, delay * 0.1)
                        total_delay = delay + jitter

                        logger.warning(
                            f"Rate limit hit (attempt {attempt + 1}/{max_retries + 1}), "
                            f"waiting {total_delay:.1f}s before retry..."
                        )
                        await asyncio.sleep(total_delay)
                        continue
                    else:
                        return result

            return result

        except Exception as e:
            last_error = e
            error_str = str(e)

            # Check if it's a rate limit exception
            if _is_rate_limit_error(e):
                if attempt < max_retries:
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = random.uniform(0, delay * 0.1)
                    total_delay = delay + jitter

                    logger.warning(
                        f"Rate limit exception (attempt {attempt + 1}/{max_retries + 1}), "
                        f"waiting {total_delay:.1f}s before retry..."
                    )
                    await asyncio.sleep(total_delay)
                    continue

            # Non-rate-limit error, don't retry
            raise

    # All retries exhausted
    return {"success": False, "error": f"Max retries exceeded: {last_error}"}


class CircuitBreaker:
    """Prevents cascading failures from persistent rate limits.

    States: CLOSED (normal), OPEN (failing, reject requests), HALF_OPEN (testing recovery)
    """

    def __init__(self, threshold: int = 5, cooldown: int = 60):
        """Initialize circuit breaker.

        Args:
            threshold: Number of consecutive failures to trigger OPEN state
            cooldown: Seconds to wait before transitioning to HALF_OPEN
        """
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.consecutive_failures = 0
        self.threshold = threshold
        self.cooldown = cooldown
        self.last_failure_time: float | None = None

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from function

        Raises:
            Exception: If circuit is OPEN or if func raises
        """
        if self.state == "OPEN":
            if self.last_failure_time is None:
                raise Exception("Circuit breaker OPEN (no recovery time set)")

            elapsed = time.time() - self.last_failure_time
            if elapsed > self.cooldown:
                self.state = "HALF_OPEN"
                logger.info(f"Circuit breaker transitioning to HALF_OPEN after {elapsed:.0f}s cooldown")
            else:
                remaining = self.cooldown - elapsed
                raise Exception(f"Circuit breaker OPEN (cooldown: {remaining:.0f}s remaining)")

        try:
            result = await func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as e:
            if _is_rate_limit_error(e):
                self.on_failure()
            raise

    def on_failure(self) -> None:
        """Handle failure - track and potentially open circuit."""
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        if self.consecutive_failures >= self.threshold:
            self.state = "OPEN"
            logger.warning(
                f"Circuit breaker OPEN after {self.consecutive_failures} consecutive failures"
            )

    def on_success(self) -> None:
        """Handle success - reset failure counter and close circuit if recovering."""
        self.consecutive_failures = 0
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            logger.info("Circuit breaker CLOSED (recovery successful)")


class GraphitiIndexer:
    """Indexes chunks into Graphiti as episodes.

    Replaces VectorIndexer for chunk storage. Accepts ChunkData objects
    and stores them as Graphiti episodes with full metadata.

    Supports both sequential and parallel indexing modes based on GRAPHITI_CONCURRENCY setting.
    Includes checkpoint/resume capability for fault tolerance.
    """

    def __init__(self, batch_size: int | None = None, enable_checkpoints: bool = True):
        """Initialize the Graphiti indexer.

        Args:
            batch_size: Number of chunks to process before logging progress
            enable_checkpoints: Whether to track indexing progress in database
        """
        self.batch_size = batch_size or settings.INDEX_BATCH_SIZE
        self._builder = None
        self._consecutive_rate_limits = 0
        self._inter_chunk_delay = INTER_CHUNK_DELAY
        self.enable_checkpoints = enable_checkpoints
        self._checkpoint_buffer: list[dict[str, Any]] = []
        self._session_id: str | None = None
        self.circuit_breaker = CircuitBreaker(
            threshold=settings.GRAPHITI_RATE_LIMIT_THRESHOLD,
            cooldown=settings.GRAPHITI_CIRCUIT_BREAKER_COOLDOWN,
        )

    def _get_builder(self):
        """Get GraphitiBuilder lazily."""
        if self._builder is None:
            self._builder = get_graphiti_builder()
        return self._builder

    async def _write_checkpoint(
        self,
        chunk_id: str,
        page_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Add checkpoint to buffer for batch write.

        Args:
            chunk_id: ID of the chunk being indexed
            page_id: ID of the page containing the chunk
            status: Status (indexed/failed/skipped)
            error_message: Optional error message if failed
        """
        if not self.enable_checkpoints:
            return

        self._checkpoint_buffer.append({
            "chunk_id": chunk_id,
            "page_id": page_id,
            "status": status,
            "error_message": error_message,
            "session_id": self._session_id,
            "indexed_at": datetime.utcnow() if status == "indexed" else None,
        })

    async def _flush_checkpoints(self) -> None:
        """Write buffered checkpoints to database in batch.

        Uses raw aiosqlite (bypassing SQLAlchemy) to avoid connection pool
        lock contention with the main application sessions.
        """
        if not self._checkpoint_buffer or not self.enable_checkpoints:
            return

        try:
            import aiosqlite

            # Extract DB path from DATABASE_URL (sqlite+aiosqlite:///./knowledge_base.db)
            db_url = settings.DATABASE_URL
            db_path = db_url.split("///")[-1] if "///" in db_url else "./knowledge_base.db"

            async with aiosqlite.connect(db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")

                for cp in self._checkpoint_buffer:
                    await db.execute(
                        """INSERT INTO indexing_checkpoints
                           (chunk_id, page_id, status, error_message, session_id, indexed_at, retry_count)
                           VALUES (?, ?, ?, ?, ?, ?, 0)
                           ON CONFLICT(chunk_id) DO UPDATE SET
                             status=excluded.status,
                             indexed_at=excluded.indexed_at,
                             error_message=excluded.error_message,
                             retry_count=retry_count+1""",
                        (
                            cp["chunk_id"],
                            cp["page_id"],
                            cp["status"],
                            cp.get("error_message"),
                            cp.get("session_id"),
                            cp["indexed_at"].isoformat() if cp.get("indexed_at") else None,
                        ),
                    )
                await db.commit()
                # Force WAL checkpoint to merge WAL data into the main DB file.
                # Without this, shutil.copyfile only copies the main file
                # (missing data still in the -wal file).
                await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

            self._checkpoint_buffer.clear()
            self._persist_db()
        except Exception as e:
            logger.error(f"Failed to flush checkpoints: {e}")

    def _persist_db(self) -> None:
        """Copy the local SQLite DB to persistent storage (e.g. GCS FUSE mount)."""
        from knowledge_base.config import settings
        if not settings.CHECKPOINT_PERSIST_PATH:
            return
        try:
            import shutil
            db_url = settings.DATABASE_URL
            local_path = db_url.split("///")[-1] if "///" in db_url else "./knowledge_base.db"
            shutil.copyfile(local_path, settings.CHECKPOINT_PERSIST_PATH)
            logger.info(f"Persisted checkpoint DB to {settings.CHECKPOINT_PERSIST_PATH}")
        except Exception as e:
            logger.warning(f"Failed to persist DB to {settings.CHECKPOINT_PERSIST_PATH}: {e}")

    async def index_chunks_direct(
        self,
        chunks: list["ChunkData | dict[str, Any]"],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Index chunks directly to Graphiti.

        Supports both sequential and parallel modes based on GRAPHITI_CONCURRENCY.
        Includes checkpoint/resume capability, retry logic, and rate limit handling.

        Args:
            chunks: List of ChunkData objects or dicts with chunk information
            progress_callback: Optional callback(indexed, total) for progress updates

        Returns:
            Number of successfully indexed chunks
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            logger.warning("Graphiti disabled, skipping indexing")
            return 0

        # Choose indexing mode based on concurrency setting
        concurrency = min(
            settings.GRAPHITI_CONCURRENCY,
            settings.GRAPHITI_MAX_CONCURRENCY,
        )

        if settings.GRAPHITI_BULK_ENABLED:
            return await self._index_chunks_adaptive_bulk(chunks, progress_callback)
        elif concurrency > 1:
            return await self._index_chunks_parallel(chunks, progress_callback)
        else:
            return await self._index_chunks_sequential(chunks, progress_callback)

    async def _index_chunks_sequential(
        self,
        chunks: list["ChunkData | dict[str, Any]"],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Index chunks sequentially (original implementation).

        Args:
            chunks: List of ChunkData objects or dicts
            progress_callback: Optional progress callback

        Returns:
            Number of successfully indexed chunks
        """
        # Generate session ID for checkpoint tracking
        self._session_id = str(uuid.uuid4())[:8]

        builder = self._get_builder()
        total = len(chunks)
        indexed = 0
        errors = 0
        rate_limit_count = 0

        logger.info(f"Indexing {total} chunks to Graphiti (sequential mode)...")

        for i, chunk in enumerate(chunks):
            chunk_id = chunk.chunk_id if hasattr(chunk, 'chunk_id') else chunk.get('chunk_id', 'unknown')
            page_id = chunk.page_id if hasattr(chunk, 'page_id') else chunk.get('page_id', 'unknown')

            try:
                # Use retry wrapper for rate limit handling
                result = await _retry_with_backoff(builder.add_chunk_episode, chunk)

                if result.get("success"):
                    indexed += 1
                    await self._write_checkpoint(chunk_id, page_id, "indexed")
                    # Reset consecutive rate limit counter on success
                    self._consecutive_rate_limits = 0
                else:
                    error_msg = result.get("error", "")
                    if result.get("reason") == "empty_content":
                        await self._write_checkpoint(chunk_id, page_id, "skipped")
                    elif _is_rate_limit_error(error_msg):
                        errors += 1
                        rate_limit_count += 1
                        self._consecutive_rate_limits += 1
                        logger.warning(f"Rate limit persisted for chunk {chunk_id} after retries")
                        await self._write_checkpoint(
                            chunk_id, page_id, "failed", str(error_msg)[:500]
                        )

                        # Increase inter-chunk delay adaptively
                        if self._consecutive_rate_limits >= 3:
                            self._inter_chunk_delay = min(self._inter_chunk_delay * 1.5, 30.0)
                            logger.info(f"Increased inter-chunk delay to {self._inter_chunk_delay:.1f}s")
                    else:
                        errors += 1
                        logger.warning(f"Failed to index chunk {chunk_id}: {result}")
                        await self._write_checkpoint(
                            chunk_id, page_id, "failed", str(error_msg)[:500]
                        )

            except Exception as e:
                errors += 1
                await self._write_checkpoint(chunk_id, page_id, "failed", str(e)[:500])
                if _is_rate_limit_error(e):
                    rate_limit_count += 1
                    self._consecutive_rate_limits += 1
                    logger.warning(f"Rate limit exception for chunk {chunk_id}: {e}")
                else:
                    logger.error(f"Error indexing chunk {chunk_id}: {e}")

            # Progress callback
            if progress_callback:
                progress_callback(i + 1, total)

            # Flush checkpoints after every chunk for crash resilience
            await self._flush_checkpoints()

            # Log batch progress
            if (i + 1) % self.batch_size == 0:
                logger.info(
                    f"Indexed {i + 1}/{total} chunks "
                    f"({indexed} success, {errors} errors, {rate_limit_count} rate limits)"
                )

            # Inter-chunk delay to avoid rate limits
            # Skip delay for the last chunk
            if i < total - 1 and self._inter_chunk_delay > 0:
                await asyncio.sleep(self._inter_chunk_delay)

        # Final flush
        await self._flush_checkpoints()

        logger.info(
            f"Completed indexing: {indexed}/{total} chunks indexed, "
            f"{errors} errors ({rate_limit_count} rate limit errors)"
        )
        return indexed

    async def _index_chunks_parallel(
        self,
        chunks: list["ChunkData | dict[str, Any]"],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Index chunks in parallel using asyncio.Semaphore.

        Args:
            chunks: List of ChunkData objects or dicts
            progress_callback: Optional progress callback

        Returns:
            Number of successfully indexed chunks
        """
        # Generate session ID for checkpoint tracking
        self._session_id = str(uuid.uuid4())[:8]

        concurrency = min(
            settings.GRAPHITI_CONCURRENCY,
            settings.GRAPHITI_MAX_CONCURRENCY,
        )
        semaphore = asyncio.Semaphore(concurrency)
        total = len(chunks)
        results = {"indexed": 0, "errors": 0, "rate_limits": 0}
        builder = self._get_builder()

        logger.info(f"Indexing {total} chunks with concurrency={concurrency}...")

        async def process_chunk(chunk: Any, index: int) -> None:
            """Process single chunk with semaphore.

            Args:
                chunk: ChunkData or dict to index
                index: Position in chunk list
            """
            async with semaphore:
                chunk_id = (
                    chunk.chunk_id
                    if hasattr(chunk, "chunk_id")
                    else chunk.get("chunk_id", "unknown")
                )
                page_id = (
                    chunk.page_id
                    if hasattr(chunk, "page_id")
                    else chunk.get("page_id", "unknown")
                )

                try:
                    result = await _retry_with_backoff(builder.add_chunk_episode, chunk)

                    if result.get("success"):
                        results["indexed"] += 1
                        await self._write_checkpoint(chunk_id, page_id, "indexed")
                    else:
                        error_msg = result.get("error", "")
                        if result.get("reason") == "empty_content":
                            await self._write_checkpoint(chunk_id, page_id, "skipped")
                        elif _is_rate_limit_error(error_msg):
                            results["errors"] += 1
                            results["rate_limits"] += 1
                            await self._write_checkpoint(
                                chunk_id, page_id, "failed", str(error_msg)[:500]
                            )
                        else:
                            results["errors"] += 1
                            await self._write_checkpoint(
                                chunk_id, page_id, "failed", str(error_msg)[:500]
                            )

                except Exception as e:
                    results["errors"] += 1
                    await self._write_checkpoint(chunk_id, page_id, "failed", str(e)[:500])
                    if _is_rate_limit_error(e):
                        results["rate_limits"] += 1

                # Progress callback
                if progress_callback:
                    progress_callback(index + 1, total)

                # Flush checkpoints after every chunk for crash resilience
                await self._flush_checkpoints()
                if (index + 1) % self.batch_size == 0:
                    logger.info(
                        f"Progress: {index + 1}/{total} - "
                        f"indexed={results['indexed']}, errors={results['errors']}"
                    )

        # Create all tasks
        tasks = [
            asyncio.create_task(process_chunk(chunk, i)) for i, chunk in enumerate(chunks)
        ]

        # Execute concurrently
        await asyncio.gather(*tasks, return_exceptions=True)

        # Final flush
        await self._flush_checkpoints()

        logger.info(
            f"Completed indexing: {results['indexed']}/{total} chunks indexed, "
            f"{results['errors']} errors ({results['rate_limits']} rate limit errors)"
        )
        return results["indexed"]

    async def _index_chunks_adaptive_bulk(
        self,
        chunks: list["ChunkData | dict[str, Any]"],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Index chunks using adaptive bulk batching (TCP congestion-control style).

        Starts with a small batch, doubles on success (slow start), switches to
        linear growth after hitting the threshold, and halves on any error with
        exponential backoff.  This finds the optimal batch size automatically.

        Args:
            chunks: List of ChunkData objects or dicts
            progress_callback: Optional progress callback

        Returns:
            Number of successfully indexed chunks
        """
        self._session_id = str(uuid.uuid4())[:8]

        builder = self._get_builder()
        graphiti = await builder._get_graphiti()

        total = len(chunks)
        indexed = 0
        errors = 0
        skipped = 0

        # Adaptive parameters
        batch_size = settings.GRAPHITI_BULK_INITIAL_BATCH
        max_batch_size = settings.GRAPHITI_BULK_MAX_BATCH
        ssthresh = max_batch_size  # slow-start threshold
        phase = "slow_start"
        consecutive_failures = 0
        base_delay = BASE_DELAY
        processed = 0  # total chunks dispatched (success + error + skip)
        chunk_attempts = 0  # total attempts on current leading chunk

        logger.info(
            f"Indexing {total} chunks via adaptive bulk "
            f"(initial_batch={batch_size}, max_batch={max_batch_size})"
        )

        # Prepare all RawEpisodes up front, tracking which chunks mapped to which
        episodes_with_chunks: list[tuple[Any, Any]] = []  # (raw_episode, chunk)
        for chunk in chunks:
            chunk_id = (
                chunk.chunk_id
                if hasattr(chunk, "chunk_id")
                else chunk.get("chunk_id", "unknown")
            )
            page_id = (
                chunk.page_id
                if hasattr(chunk, "page_id")
                else chunk.get("page_id", "unknown")
            )
            ep = builder.prepare_raw_episode(chunk)
            if ep is None:
                skipped += 1
                processed += 1
                await self._write_checkpoint(chunk_id, page_id, "skipped")
                if progress_callback:
                    progress_callback(processed, total)
                continue
            episodes_with_chunks.append((ep, chunk))

        if skipped:
            logger.info(f"Skipped {skipped} empty chunks")

        remaining = list(episodes_with_chunks)

        while remaining:
            # Take the next batch
            current_batch_size = min(batch_size, len(remaining))
            batch = remaining[:current_batch_size]

            try:
                batch_episodes = [ep for ep, _ in batch]

                result = await graphiti.add_episode_bulk(
                    batch_episodes,
                    group_id=builder.group_id,
                )

                # Success — checkpoint all chunks in batch
                for ep, chunk in batch:
                    chunk_id = (
                        chunk.chunk_id
                        if hasattr(chunk, "chunk_id")
                        else chunk.get("chunk_id", "unknown")
                    )
                    page_id = (
                        chunk.page_id
                        if hasattr(chunk, "page_id")
                        else chunk.get("page_id", "unknown")
                    )
                    indexed += 1
                    processed += 1
                    await self._write_checkpoint(chunk_id, page_id, "indexed")
                    if progress_callback:
                        progress_callback(processed, total)

                # Remove processed batch from queue
                remaining = remaining[current_batch_size:]

                # Ramp up batch size
                if phase == "slow_start":
                    batch_size *= 2
                    if batch_size >= ssthresh:
                        batch_size = ssthresh
                        phase = "congestion_avoidance"
                else:
                    batch_size += 1

                batch_size = min(batch_size, max_batch_size)
                consecutive_failures = 0
                chunk_attempts = 0

                logger.info(
                    f"Bulk batch OK: {current_batch_size} episodes | "
                    f"progress={processed}/{total} | "
                    f"next_batch={batch_size} ({phase})"
                )

                # Flush checkpoints after every successful Graphiti batch
                # (not just every INDEX_BATCH_SIZE chunks) for crash resilience
                await self._flush_checkpoints()

            except Exception as e:
                error_str = str(e)
                is_rate_limit = _is_rate_limit_error(e)
                consecutive_failures += 1
                chunk_attempts += 1

                # Halve batch size
                ssthresh = max(batch_size // 2, 1)
                batch_size = max(batch_size // 2, 1)
                phase = "congestion_avoidance"

                # Exponential backoff
                delay = min(base_delay * (2 ** (consecutive_failures - 1)), MAX_DELAY)
                jitter = random.uniform(0, delay * 0.1)
                wait = delay + jitter

                logger.warning(
                    f"Bulk batch FAILED ({current_batch_size} episodes): "
                    f"{error_str[:200]} | "
                    f"backoff={wait:.1f}s | next_batch={batch_size} | "
                    f"failures={consecutive_failures}"
                )

                # Circuit breaker: too many consecutive failures
                if consecutive_failures >= self.circuit_breaker.threshold:
                    logger.error(
                        f"Circuit breaker: {consecutive_failures} consecutive failures, "
                        f"cooling down {self.circuit_breaker.cooldown}s"
                    )
                    await asyncio.sleep(self.circuit_breaker.cooldown)
                    consecutive_failures = 0  # reset after cooldown
                else:
                    await asyncio.sleep(wait)

                # If batch_size is 1 and still failing, mark chunk as failed and move on
                if current_batch_size == 1 and chunk_attempts >= MAX_RETRIES:
                    ep, chunk = remaining[0]
                    chunk_id = (
                        chunk.chunk_id
                        if hasattr(chunk, "chunk_id")
                        else chunk.get("chunk_id", "unknown")
                    )
                    page_id = (
                        chunk.page_id
                        if hasattr(chunk, "page_id")
                        else chunk.get("page_id", "unknown")
                    )
                    errors += 1
                    processed += 1
                    await self._write_checkpoint(
                        chunk_id, page_id, "failed", error_str[:500]
                    )
                    if progress_callback:
                        progress_callback(processed, total)
                    remaining = remaining[1:]
                    consecutive_failures = 0
                    chunk_attempts = 0
                    logger.error(
                        f"Giving up on chunk {chunk_id} after {MAX_RETRIES} failures"
                    )

                # Do NOT remove the batch from remaining — it will be retried
                # with the smaller batch_size on the next iteration

        # Final flush
        await self._flush_checkpoints()

        logger.info(
            f"Completed adaptive bulk indexing: "
            f"{indexed}/{total} indexed, {errors} errors, {skipped} skipped"
        )
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
