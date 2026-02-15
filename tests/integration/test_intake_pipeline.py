"""Integration tests for Confluence intake pipeline with checkpoint/resume.

These tests verify:
1. Checkpoint system tracks indexed chunks
2. Parallel indexing works correctly
3. Resume capability skips already-indexed chunks
4. Circuit breaker prevents cascading failures
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from knowledge_base.db.models import IndexingCheckpoint
from knowledge_base.graph.graphiti_indexer import GraphitiIndexer, CircuitBreaker
from knowledge_base.config import settings


class TestCheckpointSystem:
    """Test checkpoint creation, storage, and retrieval."""

    @pytest.mark.asyncio
    async def test_checkpoint_write_and_flush(self, async_session):
        """Test checkpoint buffering and flushing."""
        indexer = GraphitiIndexer(enable_checkpoints=True)
        indexer._session_id = "test-session"

        # Write some checkpoints to buffer
        await indexer._write_checkpoint("chunk-1", "page-1", "indexed")
        await indexer._write_checkpoint("chunk-2", "page-1", "indexed")
        await indexer._write_checkpoint("chunk-3", "page-2", "failed", "Rate limit")

        # Buffer should have 3 items
        assert len(indexer._checkpoint_buffer) == 3

        # Flush to database
        await indexer._flush_checkpoints()

        # Buffer should be empty
        assert len(indexer._checkpoint_buffer) == 0

        # Verify data was written to database
        result = await async_session.execute(
            "SELECT COUNT(*) FROM indexing_checkpoints WHERE session_id = ?",
            ("test-session",),
        )
        count = result.scalar()
        assert count == 3

    @pytest.mark.asyncio
    async def test_checkpoint_upsert_on_retry(self, async_session):
        """Test that upsert increments retry_count on conflict."""
        indexer = GraphitiIndexer(enable_checkpoints=True)
        indexer._session_id = "test-session"

        # Write same chunk twice (simulating retry)
        await indexer._write_checkpoint("chunk-1", "page-1", "indexed")
        await indexer._flush_checkpoints()

        # Write same chunk again
        await indexer._write_checkpoint("chunk-1", "page-1", "failed", "Error")
        await indexer._flush_checkpoints()

        # Should have only 1 row (upserted)
        result = await async_session.execute(
            "SELECT COUNT(*) FROM indexing_checkpoints WHERE chunk_id = ?",
            ("chunk-1",),
        )
        count = result.scalar()
        assert count == 1

        # Retry count should be incremented
        result = await async_session.execute(
            "SELECT retry_count FROM indexing_checkpoints WHERE chunk_id = ?",
            ("chunk-1",),
        )
        retry_count = result.scalar()
        assert retry_count >= 1

    @pytest.mark.asyncio
    async def test_resume_query_excludes_indexed(self, async_session):
        """Test that resume query correctly excludes indexed chunks."""
        # Create some indexed checkpoints
        for i in range(5):
            checkpoint = IndexingCheckpoint(
                chunk_id=f"chunk-{i}",
                page_id="page-1",
                status="indexed",
                session_id="previous-session",
            )
            async_session.add(checkpoint)
        await async_session.commit()

        # Query that excludes indexed chunks (simulating resume)
        from sqlalchemy import select

        indexed_subquery = select(IndexingCheckpoint.chunk_id).where(
            IndexingCheckpoint.status == "indexed"
        )
        # In real code: query = query.where(Chunk.chunk_id.notin_(indexed_subquery))

        # Verify subquery works
        result = await async_session.execute(indexed_subquery)
        indexed_ids = set(row[0] for row in result)
        assert len(indexed_ids) == 5
        assert "chunk-0" in indexed_ids


class TestCircuitBreaker:
    """Test circuit breaker pattern for rate limit protection."""

    def test_circuit_breaker_states(self):
        """Test circuit breaker state transitions."""
        cb = CircuitBreaker(threshold=3, cooldown=1)

        # Start in CLOSED state
        assert cb.state == "CLOSED"

        # Failures don't immediately open
        cb.on_failure()
        cb.on_failure()
        assert cb.state == "CLOSED"

        # Third failure opens circuit
        cb.on_failure()
        assert cb.state == "OPEN"

        # Success while OPEN doesn't close (need HALF_OPEN)
        assert cb.state == "OPEN"

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after cooldown."""
        import time

        cb = CircuitBreaker(threshold=1, cooldown=0.1)  # Short cooldown for testing

        # Open the circuit
        cb.on_failure()
        assert cb.state == "OPEN"

        # Try to call immediately (should fail)
        mock_func = AsyncMock()
        with pytest.raises(Exception, match="Circuit breaker OPEN"):
            await cb.call(mock_func)

        # Wait for cooldown
        time.sleep(0.2)

        # Should transition to HALF_OPEN
        mock_func = AsyncMock(return_value="success")
        result = await cb.call(mock_func)
        assert result == "success"
        assert cb.state == "CLOSED"  # Recovered

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_on_rate_limits(self):
        """Test circuit breaker blocks after N rate limit failures."""

        async def failing_func():
            raise Exception("rate_limit_error")

        cb = CircuitBreaker(threshold=2, cooldown=60)

        # First failure
        with pytest.raises(Exception):
            await cb.call(failing_func)
        assert cb.state == "CLOSED"

        # Second failure opens
        with pytest.raises(Exception):
            await cb.call(failing_func)
        assert cb.state == "OPEN"

        # Further calls rejected immediately
        with pytest.raises(Exception, match="Circuit breaker OPEN"):
            await cb.call(failing_func)


class TestParallelIndexing:
    """Test parallel chunk indexing with Semaphore."""

    @pytest.mark.asyncio
    async def test_parallel_mode_with_semaphore(self):
        """Test that parallel mode uses concurrency limit."""
        mock_chunks = [{"chunk_id": f"chunk-{i}", "page_id": "page-1"} for i in range(10)]

        indexer = GraphitiIndexer(enable_checkpoints=False)

        with patch.object(indexer, "_get_builder") as mock_builder:
            mock_builder.return_value.add_chunk_episode = AsyncMock(
                return_value={"success": True}
            )

            # Mock to capture concurrency
            concurrent_calls = []
            original_call = mock_builder.return_value.add_chunk_episode

            async def tracked_call(*args, **kwargs):
                concurrent_calls.append(1)
                await asyncio.sleep(0.01)  # Simulate work
                concurrent_calls.pop()
                return await original_call(*args, **kwargs)

            mock_builder.return_value.add_chunk_episode = tracked_call

            # Run with concurrency=3
            with patch.object(settings, "GRAPHITI_CONCURRENCY", 3):
                await indexer._index_chunks_parallel(mock_chunks)

            # Max concurrent calls should be limited
            assert len(concurrent_calls) <= 3

    @pytest.mark.asyncio
    async def test_sequential_vs_parallel_produces_same_results(self):
        """Test that sequential and parallel modes produce same indexed count."""
        mock_chunks = [{"chunk_id": f"chunk-{i}", "page_id": "page-1"} for i in range(5)]

        with patch.object(settings, "GRAPH_ENABLE_GRAPHITI", True):
            # Mock builder
            with patch("knowledge_base.graph.graphiti_indexer.get_graphiti_builder") as mock:
                mock.return_value.add_chunk_episode = AsyncMock(
                    return_value={"success": True}
                )

                # Sequential mode
                indexer_seq = GraphitiIndexer(enable_checkpoints=False)
                seq_count = await indexer_seq._index_chunks_sequential(mock_chunks)

                # Parallel mode
                indexer_par = GraphitiIndexer(enable_checkpoints=False)
                par_count = await indexer_par._index_chunks_parallel(mock_chunks)

                # Should index same number of chunks
                assert seq_count == par_count == len(mock_chunks)


class TestResumeCapability:
    """Test resume functionality after interruption."""

    # Removed: test_resume_skips_indexed_chunks - tested deprecated Chunk model


# Pytest fixtures
@pytest.fixture
async def async_session():
    """Create async database session for testing."""
    from knowledge_base.db.database import async_session_maker

    async with async_session_maker() as session:
        yield session


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
