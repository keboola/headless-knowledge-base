"""Batch embedding generation for resolved entities and edges.

Uses the existing ``vectorstore.embeddings`` infrastructure (Vertex AI
text-embedding-005) to generate 768-dim vectors for:
- Entity canonical names (stored on ``ResolvedEntity.name_embedding``)
- Relationship facts (stored on ``ResolvedRelationship.fact_embedding``)

Supports two modes:
1. **In-memory** (``embed_entities`` / ``embed_edges``): stores embeddings on
   the model objects.  Suitable for small datasets that fit in memory.
2. **Streaming** (``stream_embed_entities`` / ``stream_embed_edges``): calls a
   callback with each batch of (uuid, embedding) pairs so the caller can flush
   to Neo4j immediately.  Only one batch (~60 KB) is in memory at a time,
   making this safe for 100K+ items within 8 Gi Cloud Run jobs.

Rate-limit (429) errors are handled with exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from knowledge_base.batch.models import ResolvedEntity, ResolvedRelationship
from knowledge_base.config import settings
from knowledge_base.vectorstore.embeddings import BaseEmbeddings, get_embeddings

logger = logging.getLogger(__name__)

# Retry constants for 429 handling
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 5.0  # seconds
_MAX_BACKOFF = 120.0  # seconds


class BatchEmbedder:
    """Generate embeddings for resolved entities and relationships in bulk.

    Reuses the project's embedding provider (``get_embeddings()``) which
    returns a ``VertexAIEmbeddings`` instance in production.  Batching
    and concurrency are controlled by settings to stay within API limits.
    """

    def __init__(self) -> None:
        self._embedder: BaseEmbeddings = get_embeddings()
        self._batch_size: int = settings.VERTEX_AI_BATCH_SIZE
        self._concurrency: int = settings.BATCH_EMBEDDING_CONCURRENCY

    # ------------------------------------------------------------------
    # Public API -- streaming (preferred for large datasets)
    # ------------------------------------------------------------------

    async def stream_embed_entities(
        self,
        entities: list[ResolvedEntity],
        on_batch: Callable[[list[tuple[str, list[float]]]], Awaitable[None]],
    ) -> int:
        """Embed entity names and stream results via *on_batch* callback.

        Instead of accumulating all embeddings in memory, each completed
        API batch is immediately forwarded to *on_batch* as a list of
        ``(entity_uuid, embedding_vector)`` pairs, allowing the caller
        to write to Neo4j and release memory.

        Args:
            entities: Resolved entities to embed.
            on_batch: Async callback receiving ``[(uuid, [float, ...])]``.

        Returns:
            Number of entities embedded.
        """
        to_embed = [
            (e.uuid, e.canonical_name)
            for e in entities
            if not e.name_embedding and e.canonical_name.strip()
        ]
        if not to_embed:
            logger.info(
                "All %d entities already have embeddings -- skipping",
                len(entities),
            )
            return 0

        logger.info(
            "Streaming %d entity name embeddings (%d already done)",
            len(to_embed),
            len(entities) - len(to_embed),
        )

        return await self._stream_embed(to_embed, on_batch, label="entity names")

    async def stream_embed_edges(
        self,
        relationships: list[ResolvedRelationship],
        on_batch: Callable[[list[tuple[str, list[float]]]], Awaitable[None]],
    ) -> int:
        """Embed edge facts and stream results via *on_batch* callback.

        Args:
            relationships: Resolved relationships to embed.
            on_batch: Async callback receiving ``[(uuid, [float, ...])]``.

        Returns:
            Number of edges embedded.
        """
        to_embed = [
            (r.uuid, r.fact)
            for r in relationships
            if not r.fact_embedding and r.fact.strip()
        ]
        if not to_embed:
            logger.info(
                "All %d edges already have embeddings -- skipping",
                len(relationships),
            )
            return 0

        logger.info(
            "Streaming %d edge fact embeddings (%d already done)",
            len(to_embed),
            len(relationships) - len(to_embed),
        )

        return await self._stream_embed(to_embed, on_batch, label="edge facts")

    # ------------------------------------------------------------------
    # Public API -- in-memory (convenience for small datasets / tests)
    # ------------------------------------------------------------------

    async def embed_entities(self, entities: list[ResolvedEntity]) -> None:
        """Embed each entity's canonical name and store on ``name_embedding``.

        Skips entities that already have an embedding (for resume).
        Skips entities with empty names (Vertex AI rejects empty text).
        """
        if not entities:
            return

        to_embed = [e for e in entities if not e.name_embedding and e.canonical_name.strip()]
        if not to_embed:
            logger.info("All %d entities already have embeddings -- skipping", len(entities))
            return

        logger.info(
            "Embedding %d entity names (%d already done)",
            len(to_embed),
            len(entities) - len(to_embed),
        )

        texts = [e.canonical_name for e in to_embed]
        embeddings = await self._embed_all(texts, label="entity names")

        for entity, embedding in zip(to_embed, embeddings):
            entity.name_embedding = embedding

        logger.info("Embedded %d/%d entity names", len(embeddings), len(entities))

    async def embed_edges(self, relationships: list[ResolvedRelationship]) -> None:
        """Embed each relationship's fact and store on ``fact_embedding``.

        Skips relationships that already have an embedding (for resume).
        """
        if not relationships:
            return

        to_embed = [r for r in relationships if not r.fact_embedding and r.fact.strip()]
        if not to_embed:
            logger.info("All %d edges already have embeddings -- skipping", len(relationships))
            return

        logger.info(
            "Embedding %d edge facts (%d already done)",
            len(to_embed),
            len(relationships) - len(to_embed),
        )

        texts = [r.fact for r in to_embed]
        embeddings = await self._embed_all(texts, label="edge facts")

        for relationship, embedding in zip(to_embed, embeddings):
            relationship.fact_embedding = embedding

        logger.info("Embedded %d/%d edge facts", len(embeddings), len(relationships))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _embed_batch_with_retry(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch with exponential backoff on 429 errors."""
        backoff = _INITIAL_BACKOFF
        for attempt in range(_MAX_RETRIES):
            try:
                return await self._embedder.embed(texts)
            except Exception as exc:
                # Check for 429 / ResourceExhausted
                exc_str = str(exc)
                is_rate_limit = (
                    "429" in exc_str
                    or "ResourceExhausted" in type(exc).__name__
                    or "Resource exhausted" in exc_str
                )
                if is_rate_limit and attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "Rate limited (attempt %d/%d), backing off %.0fs",
                        attempt + 1,
                        _MAX_RETRIES,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _MAX_BACKOFF)
                    continue
                raise

        # Should never reach here, but just in case
        return await self._embedder.embed(texts)

    async def _stream_embed(
        self,
        items: list[tuple[str, str]],
        on_batch: Callable[[list[tuple[str, list[float]]]], Awaitable[None]],
        label: str,
    ) -> int:
        """Core streaming embed: embed texts in batches and call on_batch for each.

        Args:
            items: List of (uuid, text) pairs to embed.
            on_batch: Async callback receiving [(uuid, embedding)] pairs.
            label: Human-readable label for logging.

        Returns:
            Total items embedded.
        """
        total = len(items)
        if total == 0:
            return 0

        # Split into API-sized batches
        batches: list[list[tuple[str, str]]] = [
            items[i : i + self._batch_size]
            for i in range(0, total, self._batch_size)
        ]

        embedded_count = 0
        semaphore = asyncio.Semaphore(self._concurrency)
        start_time = time.monotonic()

        async def _process_and_flush(batch: list[tuple[str, str]]) -> int:
            """Embed one batch and flush to Neo4j via callback."""
            uuids = [uid for uid, _ in batch]
            texts = [text for _, text in batch]
            async with semaphore:
                embeddings = await self._embed_batch_with_retry(texts)
            pairs = list(zip(uuids, embeddings))
            await on_batch(pairs)
            return len(pairs)

        # Process in waves to limit concurrent task count.
        # Each wave has up to concurrency * 4 batches.
        wave_size = self._concurrency * 4
        for wave_start in range(0, len(batches), wave_size):
            wave = batches[wave_start : wave_start + wave_size]
            tasks = [
                asyncio.create_task(_process_and_flush(batch)) for batch in wave
            ]

            for coro in asyncio.as_completed(tasks):
                count = await coro
                embedded_count += count

            elapsed = time.monotonic() - start_time
            rate = embedded_count / elapsed if elapsed > 0 else 0
            logger.info(
                "Streamed %d/%d %s to Neo4j  (%.1f items/s)",
                embedded_count,
                total,
                label,
                rate,
            )

            # Small delay between waves to smooth out rate limits
            if wave_start + wave_size < len(batches):
                await asyncio.sleep(0.5)

        logger.info(
            "Streaming complete: %d %s embedded in %.1fs",
            embedded_count,
            label,
            time.monotonic() - start_time,
        )
        return embedded_count

    async def _embed_all(self, texts: list[str], label: str) -> list[list[float]]:
        """Embed an arbitrarily long list of texts with batching and concurrency.

        NOTE: This accumulates all embeddings in memory.  For large datasets
        (>50K items), use ``stream_embed_entities``/``stream_embed_edges``
        instead.

        Parameters
        ----------
        texts
            All texts to embed.
        label
            Human-readable label for progress logging.

        Returns
        -------
        list[list[float]]
            Embedding vectors in the same order as *texts*.
        """
        total = len(texts)
        if total == 0:
            return []

        # Split into batches
        batches: list[list[str]] = [
            texts[i : i + self._batch_size]
            for i in range(0, total, self._batch_size)
        ]

        all_embeddings: list[list[float]] = []
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _process_batch(batch: list[str]) -> list[list[float]]:
            async with semaphore:
                return await self._embed_batch_with_retry(batch)

        # Process in waves to avoid scheduling too many tasks at once.
        wave_size = self._concurrency * 4
        for wave_start in range(0, len(batches), wave_size):
            wave = batches[wave_start : wave_start + wave_size]
            tasks = [asyncio.create_task(_process_batch(batch)) for batch in wave]

            for coro in asyncio.as_completed(tasks):
                batch_result = await coro
                all_embeddings.extend(batch_result)

            logger.info("Embedded %d/%d %s", len(all_embeddings), total, label)

            if wave_start + wave_size < len(batches):
                await asyncio.sleep(0.5)

        return all_embeddings
