"""Batch embedding generation for resolved entities and edges.

Uses the existing ``vectorstore.embeddings`` infrastructure (Vertex AI
text-embedding-005) to generate 768-dim vectors for:
- Entity canonical names (stored on ``ResolvedEntity.name_embedding``)
- Relationship facts (stored on ``ResolvedRelationship.fact_embedding``)

Embeddings are computed in batches of ``settings.VERTEX_AI_BATCH_SIZE``
with up to ``settings.BATCH_EMBEDDING_CONCURRENCY`` parallel batches to
maximise throughput while respecting Vertex AI rate limits.

Rate-limit (429) errors are handled with exponential backoff and the
concurrency is temporarily reduced to avoid cascading failures.
"""

from __future__ import annotations

import asyncio
import logging
import time

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
    # Public API
    # ------------------------------------------------------------------

    async def embed_entities(self, entities: list[ResolvedEntity]) -> None:
        """Embed each entity's canonical name and store on ``name_embedding``.

        Skips entities that already have an embedding (for resume).
        """
        if not entities:
            return

        # Filter to entities that still need embedding
        to_embed = [e for e in entities if not e.name_embedding]
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

        to_embed = [r for r in relationships if not r.fact_embedding]
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

    async def _embed_all(self, texts: list[str], label: str) -> list[list[float]]:
        """Embed an arbitrarily long list of texts with batching and concurrency.

        Uses a semaphore to limit concurrency and processes batches
        sequentially on 429 errors (reduces concurrency temporarily).

        Parameters
        ----------
        texts
            All texts to embed.
        label
            Human-readable label for progress logging (e.g. "entity names").

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
        embedded_count = 0
        log_interval = max(1, len(batches) // 20)  # Log ~20 times

        async def _process_batch(batch: list[str]) -> list[list[float]]:
            async with semaphore:
                return await self._embed_batch_with_retry(batch)

        # Process in waves to avoid scheduling 10K+ tasks at once.
        # Each wave has up to concurrency * 4 batches.
        wave_size = self._concurrency * 4
        for wave_start in range(0, len(batches), wave_size):
            wave = batches[wave_start : wave_start + wave_size]
            tasks = [asyncio.create_task(_process_batch(batch)) for batch in wave]

            for i, task in enumerate(asyncio.as_completed(tasks)):
                batch_result = await task
                all_embeddings.extend(batch_result)
                embedded_count += len(wave[min(i, len(wave) - 1)])

            # Log progress after each wave
            logger.info("Embedded %d/%d %s", len(all_embeddings), total, label)

            # Small delay between waves to smooth out rate limits
            if wave_start + wave_size < len(batches):
                await asyncio.sleep(0.5)

        return all_embeddings
