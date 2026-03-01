"""Batch embedding generation for resolved entities and edges.

Uses the existing ``vectorstore.embeddings`` infrastructure (Vertex AI
text-embedding-005) to generate 768-dim vectors for:
- Entity canonical names (stored on ``ResolvedEntity.name_embedding``)
- Relationship facts (stored on ``ResolvedRelationship.fact_embedding``)

Embeddings are computed in batches of ``settings.VERTEX_AI_BATCH_SIZE``
with up to ``settings.BATCH_EMBEDDING_CONCURRENCY`` parallel batches to
maximise throughput while respecting Vertex AI rate limits.
"""

from __future__ import annotations

import asyncio
import logging

from knowledge_base.batch.models import ResolvedEntity, ResolvedRelationship
from knowledge_base.config import settings
from knowledge_base.vectorstore.embeddings import BaseEmbeddings, get_embeddings

logger = logging.getLogger(__name__)


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

        Parameters
        ----------
        entities
            Resolved entities whose ``name_embedding`` field will be
            populated in-place.
        """
        if not entities:
            return

        texts = [e.canonical_name for e in entities]
        embeddings = await self._embed_all(texts, label="entity names")

        for entity, embedding in zip(entities, embeddings):
            entity.name_embedding = embedding

        logger.info("Embedded %d/%d entity names", len(embeddings), len(entities))

    async def embed_edges(self, relationships: list[ResolvedRelationship]) -> None:
        """Embed each relationship's fact and store on ``fact_embedding``.

        Parameters
        ----------
        relationships
            Resolved relationships whose ``fact_embedding`` field will be
            populated in-place.
        """
        if not relationships:
            return

        texts = [r.fact for r in relationships]
        embeddings = await self._embed_all(texts, label="edge facts")

        for relationship, embedding in zip(relationships, embeddings):
            relationship.fact_embedding = embedding

        logger.info("Embedded %d/%d edge facts", len(embeddings), len(relationships))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch of texts via the embedding provider.

        Returns
        -------
        list[list[float]]
            One 768-dim vector per input text.
        """
        return await self._embedder.embed(texts)

    async def _embed_all(self, texts: list[str], label: str) -> list[list[float]]:
        """Embed an arbitrarily long list of texts with batching and concurrency.

        Splits *texts* into chunks of ``_batch_size``, then processes up
        to ``_concurrency`` chunks in parallel using an ``asyncio.Semaphore``.

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

        results: list[list[list[float]]] = [[] for _ in batches]
        semaphore = asyncio.Semaphore(self._concurrency)
        embedded_count = 0

        async def _process_batch(idx: int, batch: list[str]) -> None:
            nonlocal embedded_count
            async with semaphore:
                batch_embeddings = await self._embed_batch(batch)
                results[idx] = batch_embeddings
                embedded_count += len(batch)
                logger.info(
                    "Embedded %d/%d %s", embedded_count, total, label
                )

        # Launch all batches; the semaphore limits concurrency
        tasks = [
            asyncio.create_task(_process_batch(idx, batch))
            for idx, batch in enumerate(batches)
        ]
        await asyncio.gather(*tasks)

        # Flatten in order
        all_embeddings: list[list[float]] = []
        for batch_result in results:
            all_embeddings.extend(batch_result)

        return all_embeddings
