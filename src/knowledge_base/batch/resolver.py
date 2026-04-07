"""Entity resolution for the batch import pipeline.

Resolves raw LLM-extracted entities and relationships into deduplicated,
UUID-assigned objects ready for Neo4j import.  This module does NOT make
any LLM calls -- all resolution is deterministic.

Algorithm overview:
1. Collect raw entities from every chunk extraction.
2. Normalize names (lowercase, strip, collapse whitespace).
3. Group by (normalized_name, entity_type) -- exact match dedup.
4. Assign stable UUIDs (uuid4) to each unique entity group.
5. Map every extracted relationship to resolved entity UUIDs.
6. Deduplicate relationships by (source_uuid, target_uuid, normalized_name).
7. Drop self-referential edges created by resolution merges.
8. Attach ``mentioned_in_episodes`` to each entity.

Optional fuzzy merge (BATCH_ENTITY_FUZZY_MERGE_ENABLED):
    Between steps 3 and 4, an embedding-based similarity merge clusters
    near-duplicates (e.g. "Platform Team" vs "platform-team") that
    differ beyond simple normalisation.  The threshold is configurable
    via ``settings.BATCH_ENTITY_SIMILARITY_THRESHOLD`` (default 0.85
    cosine).  Groups are partitioned by entity_type (never merges
    across types), canonical names are embedded, and single-linkage
    clustering via union-find merges groups above the threshold.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import uuid
from collections import defaultdict

from knowledge_base.batch.models import (
    ChunkExtractionResult,
    ResolvedEntity,
    ResolvedRelationship,
)
from knowledge_base.config import settings

logger = logging.getLogger(__name__)

# Pre-compiled regex for whitespace normalisation
_MULTI_WS = re.compile(r"\s+")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _normalize_name(raw: str) -> str:
    """Normalize an entity or relationship name for grouping.

    Lowercases, strips leading/trailing whitespace, and collapses
    consecutive whitespace characters into a single space.
    """
    return _MULTI_WS.sub(" ", raw.strip().lower())


class EntityResolver:
    """Deterministic entity & relationship resolution (no LLM calls).

    Parameters
    ----------
    similarity_threshold
        Reserved for future embedding-based fuzzy merge.  Currently
        read from ``settings.BATCH_ENTITY_SIMILARITY_THRESHOLD`` but
        only stored -- not yet used.
    """

    def __init__(
        self,
        similarity_threshold: float | None = None,
    ) -> None:
        self.similarity_threshold: float = (
            similarity_threshold
            if similarity_threshold is not None
            else settings.BATCH_ENTITY_SIMILARITY_THRESHOLD
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve(
        self,
        extractions: dict[str, ChunkExtractionResult],
        episode_uuids: dict[str, str],
    ) -> tuple[list[ResolvedEntity], list[ResolvedRelationship]]:
        """Resolve raw extractions into deduplicated entities and relationships.

        Parameters
        ----------
        extractions
            Mapping of ``chunk_id`` -> ``ChunkExtractionResult`` (the
            structured output produced by the Gemini Batch API extractor).
        episode_uuids
            Mapping of ``chunk_id`` -> episode UUID that was already
            created in Neo4j for the corresponding chunk.

        Returns
        -------
        tuple[list[ResolvedEntity], list[ResolvedRelationship]]
            Deduplicated entities and relationships, each with assigned
            UUIDs and cross-references to episode UUIDs.
        """
        logger.info(
            "Starting entity resolution for %d chunks", len(extractions)
        )

        # Step 1-3: Collect raw entities, normalise, group by exact match
        entity_groups = self._group_entities(extractions)
        logger.info(
            "Grouped raw entities into %d unique (name, type) groups",
            len(entity_groups),
        )

        # Optional: fuzzy merge near-duplicates via embedding similarity
        if settings.BATCH_ENTITY_FUZZY_MERGE_ENABLED:
            entity_groups = await self._fuzzy_merge_groups(entity_groups)
            logger.info(
                "After fuzzy merge: %d entity groups", len(entity_groups)
            )

        # Step 4-5: Assign UUIDs and build lookup registry
        resolved_entities, registry = self._build_registry(entity_groups)
        logger.info(
            "Built entity registry with %d resolved entities "
            "(%d raw name variants)",
            len(resolved_entities),
            sum(len(e.raw_names) for e in resolved_entities),
        )

        # Step 6-8: Process, deduplicate, and filter relationships
        resolved_relationships = self._resolve_relationships(
            extractions, episode_uuids, registry
        )
        logger.info(
            "Resolved %d unique relationships", len(resolved_relationships)
        )

        # Step 9: Build mentioned_in_episodes on each entity
        self._attach_episode_mentions(
            resolved_entities, extractions, episode_uuids, registry
        )

        logger.info(
            "Entity resolution complete: %d entities, %d relationships",
            len(resolved_entities),
            len(resolved_relationships),
        )
        return resolved_entities, resolved_relationships

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _group_entities(
        self,
        extractions: dict[str, ChunkExtractionResult],
    ) -> dict[tuple[str, str], _EntityGroup]:
        """Collect and group entities by (normalized_name, entity_type).

        Returns a mapping from the grouping key to an ``_EntityGroup``
        that accumulates all surface-form names and summaries.
        """
        groups: dict[tuple[str, str], _EntityGroup] = {}

        for chunk_id, result in extractions.items():
            for entity in result.entities:
                norm_name = _normalize_name(entity.name)
                norm_type = _normalize_name(entity.entity_type)
                key = (norm_name, norm_type)

                if key not in groups:
                    groups[key] = _EntityGroup(
                        normalized_name=norm_name,
                        entity_type=norm_type,
                    )

                groups[key].raw_names.add(entity.name)
                groups[key].summaries.append(entity.summary)
                groups[key].source_chunk_ids.add(chunk_id)

        return groups

    def _build_registry(
        self,
        entity_groups: dict[tuple[str, str], _EntityGroup],
    ) -> tuple[list[ResolvedEntity], dict[tuple[str, str], ResolvedEntity]]:
        """Assign UUIDs and build a lookup from (raw_name, type) -> ResolvedEntity.

        The registry maps *every* (normalized raw_name, normalized type)
        pair to its resolved entity, enabling O(1) lookup during
        relationship resolution.
        """
        resolved: list[ResolvedEntity] = []
        registry: dict[tuple[str, str], ResolvedEntity] = {}

        for (norm_name, norm_type), group in entity_groups.items():
            # Pick the longest raw name as canonical (most informative)
            canonical = max(group.raw_names, key=len)

            # Pick the longest summary (most context)
            summary = max(group.summaries, key=len) if group.summaries else ""

            entity = ResolvedEntity(
                uuid=str(uuid.uuid4()),
                canonical_name=canonical,
                entity_type=group.entity_type,
                summary=summary,
                raw_names=set(group.raw_names),
            )
            resolved.append(entity)

            # Register every (normalized raw variant, type) for lookup
            for raw in group.raw_names:
                registry[(_normalize_name(raw), norm_type)] = entity

        # Filter out entities with empty canonical names (bad LLM extraction output)
        before_count = len(resolved)
        resolved = [e for e in resolved if e.canonical_name.strip()]
        if len(resolved) < before_count:
            logger.warning(
                "Filtered %d entities with empty canonical names",
                before_count - len(resolved),
            )

        return resolved, registry

    def _resolve_relationships(
        self,
        extractions: dict[str, ChunkExtractionResult],
        episode_uuids: dict[str, str],
        registry: dict[tuple[str, str], ResolvedEntity],
    ) -> list[ResolvedRelationship]:
        """Map raw relationships to resolved entity UUIDs, deduplicate, and filter.

        Steps:
        - Look up source and target entities in the registry.
        - Skip relationships where either entity cannot be resolved.
        - Deduplicate by (source_uuid, target_uuid, normalized_relationship_name).
        - Merge episode_uuids and keep the longest fact text.
        - Drop self-referential edges.
        """
        # Accumulator: (src_uuid, tgt_uuid, norm_rel_name) -> _RelGroup
        rel_groups: dict[tuple[str, str, str], _RelGroup] = {}
        skipped_missing = 0
        skipped_self_ref = 0

        for chunk_id, result in extractions.items():
            episode_uuid = episode_uuids.get(chunk_id)
            if episode_uuid is None:
                logger.warning(
                    "No episode UUID for chunk %s -- skipping its relationships",
                    chunk_id,
                )
                continue

            # Build a quick name->type index for this chunk's entities
            # so we can look up the entity type when resolving relationships
            chunk_entity_types: dict[str, str] = {}
            for ent in result.entities:
                chunk_entity_types[_normalize_name(ent.name)] = _normalize_name(
                    ent.entity_type
                )

            for rel in result.relationships:
                # Resolve source entity
                src_norm = _normalize_name(rel.source_entity)
                src_type = chunk_entity_types.get(src_norm)
                if src_type is None:
                    skipped_missing += 1
                    logger.debug(
                        "Source entity %r not found in chunk %s entities -- skipping relationship",
                        rel.source_entity,
                        chunk_id,
                    )
                    continue

                src_entity = registry.get((src_norm, src_type))
                if src_entity is None:
                    skipped_missing += 1
                    logger.debug(
                        "Source entity (%r, %r) not in registry -- skipping",
                        src_norm,
                        src_type,
                    )
                    continue

                # Resolve target entity
                tgt_norm = _normalize_name(rel.target_entity)
                tgt_type = chunk_entity_types.get(tgt_norm)
                if tgt_type is None:
                    skipped_missing += 1
                    logger.debug(
                        "Target entity %r not found in chunk %s entities -- skipping relationship",
                        rel.target_entity,
                        chunk_id,
                    )
                    continue

                tgt_entity = registry.get((tgt_norm, tgt_type))
                if tgt_entity is None:
                    skipped_missing += 1
                    logger.debug(
                        "Target entity (%r, %r) not in registry -- skipping",
                        tgt_norm,
                        tgt_type,
                    )
                    continue

                # Drop self-referential edges (step 8)
                if src_entity.uuid == tgt_entity.uuid:
                    skipped_self_ref += 1
                    logger.debug(
                        "Dropping self-referential edge: %r -> %r (both resolve to %s)",
                        rel.source_entity,
                        rel.target_entity,
                        src_entity.canonical_name,
                    )
                    continue

                # Deduplication key
                norm_rel = _normalize_name(rel.relationship_name)
                dedup_key = (src_entity.uuid, tgt_entity.uuid, norm_rel)

                if dedup_key not in rel_groups:
                    rel_groups[dedup_key] = _RelGroup(
                        source_entity_uuid=src_entity.uuid,
                        target_entity_uuid=tgt_entity.uuid,
                        relationship_name=rel.relationship_name,
                    )

                rel_groups[dedup_key].facts.append(rel.fact)
                rel_groups[dedup_key].episode_uuids.add(episode_uuid)

        if skipped_missing:
            logger.info(
                "Skipped %d relationship(s) due to unresolvable entities",
                skipped_missing,
            )
        if skipped_self_ref:
            logger.info(
                "Dropped %d self-referential edge(s)", skipped_self_ref
            )

        # Convert accumulated groups into resolved relationships
        resolved: list[ResolvedRelationship] = []
        for group in rel_groups.values():
            # Pick the longest fact (most informative)
            best_fact = max(group.facts, key=len) if group.facts else ""

            resolved.append(
                ResolvedRelationship(
                    uuid=str(uuid.uuid4()),
                    source_entity_uuid=group.source_entity_uuid,
                    target_entity_uuid=group.target_entity_uuid,
                    relationship_name=group.relationship_name,
                    fact=best_fact,
                    episode_uuids=sorted(group.episode_uuids),
                )
            )

        return resolved

    def _attach_episode_mentions(
        self,
        resolved_entities: list[ResolvedEntity],
        extractions: dict[str, ChunkExtractionResult],
        episode_uuids: dict[str, str],
        registry: dict[tuple[str, str], ResolvedEntity],
    ) -> None:
        """Populate ``mentioned_in_episodes`` on each resolved entity.

        For every chunk, look up which resolved entity each raw
        extraction maps to and add the chunk's episode UUID.
        """
        # entity UUID -> set of episode UUIDs
        mentions: dict[str, set[str]] = defaultdict(set)

        for chunk_id, result in extractions.items():
            episode_uuid = episode_uuids.get(chunk_id)
            if episode_uuid is None:
                continue

            for ent in result.entities:
                norm_name = _normalize_name(ent.name)
                norm_type = _normalize_name(ent.entity_type)
                resolved = registry.get((norm_name, norm_type))
                if resolved is not None:
                    mentions[resolved.uuid].add(episode_uuid)

        # Write back to entity objects
        for entity in resolved_entities:
            entity.mentioned_in_episodes = sorted(
                mentions.get(entity.uuid, set())
            )

        total_mentions = sum(
            len(e.mentioned_in_episodes) for e in resolved_entities
        )
        logger.debug(
            "Attached %d total episode mentions across %d entities",
            total_mentions,
            len(resolved_entities),
        )


    async def _fuzzy_merge_groups(
        self,
        entity_groups: dict[tuple[str, str], _EntityGroup],
    ) -> dict[tuple[str, str], _EntityGroup]:
        """Merge near-duplicate entity groups using embedding similarity.

        Partitions groups by entity_type (never merges across types),
        embeds all canonical names, computes pairwise cosine similarity,
        and uses single-linkage clustering (union-find) to merge groups
        above the similarity threshold.
        """
        from knowledge_base.vectorstore.embeddings import get_embeddings

        embedder = get_embeddings()

        # Partition groups by entity_type
        type_buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for key in entity_groups:
            _norm_name, norm_type = key
            type_buckets[norm_type].append(key)

        merged_groups: dict[tuple[str, str], _EntityGroup] = {}
        total_merges = 0

        for entity_type, keys in type_buckets.items():
            if len(keys) <= 1:
                # Nothing to merge for a single group
                for k in keys:
                    merged_groups[k] = entity_groups[k]
                continue

            # Embed canonical names in batches
            canonical_names = [
                entity_groups[k].normalized_name for k in keys
            ]

            batch_size = settings.BATCH_FUZZY_MERGE_BATCH_SIZE
            all_embeddings: list[list[float]] = []
            for i in range(0, len(canonical_names), batch_size):
                batch = canonical_names[i : i + batch_size]
                batch_embeddings = await embedder.embed(batch)
                all_embeddings.extend(batch_embeddings)
                # Rate-limit between batches to avoid Vertex AI 429
                if i + batch_size < len(canonical_names):
                    await asyncio.sleep(1.0)

            # Pairwise cosine similarity + union-find clustering
            n = len(keys)
            uf = _UnionFind(n)

            for i in range(n):
                for j in range(i + 1, n):
                    sim = _cosine_similarity(all_embeddings[i], all_embeddings[j])
                    if sim >= self.similarity_threshold:
                        uf.union(i, j)
                        logger.debug(
                            "Fuzzy merge: %r <-> %r (sim=%.4f, type=%s)",
                            canonical_names[i],
                            canonical_names[j],
                            sim,
                            entity_type,
                        )

            # Build clusters from union-find
            clusters: dict[int, list[int]] = defaultdict(list)
            for i in range(n):
                clusters[uf.find(i)].append(i)

            # Merge each cluster into a single group
            for members in clusters.values():
                if len(members) > 1:
                    total_merges += len(members) - 1

                # Use the first member's key as the canonical key
                primary_key = keys[members[0]]
                primary_group = _EntityGroup(
                    normalized_name=entity_groups[primary_key].normalized_name,
                    entity_type=entity_type,
                )

                for idx in members:
                    source_group = entity_groups[keys[idx]]
                    primary_group.raw_names.update(source_group.raw_names)
                    primary_group.summaries.extend(source_group.summaries)
                    primary_group.source_chunk_ids.update(
                        source_group.source_chunk_ids
                    )

                merged_groups[primary_key] = primary_group

        if total_merges > 0:
            logger.info(
                "Fuzzy merge reduced groups by %d (from %d to %d)",
                total_merges,
                len(entity_groups),
                len(merged_groups),
            )

        return merged_groups


# ---------------------------------------------------------------------------
# Union-Find for single-linkage clustering
# ---------------------------------------------------------------------------


class _UnionFind:
    """Simple union-find (disjoint set) for clustering."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        px, py = self.find(x), self.find(y)
        if px != py:
            self.parent[px] = py


# ---------------------------------------------------------------------------
# Internal grouping dataclasses
# ---------------------------------------------------------------------------


class _EntityGroup:
    """Accumulator for raw entities that share a normalised (name, type) key."""

    __slots__ = ("normalized_name", "entity_type", "raw_names", "summaries", "source_chunk_ids")

    def __init__(self, normalized_name: str, entity_type: str) -> None:
        self.normalized_name = normalized_name
        self.entity_type = entity_type
        self.raw_names: set[str] = set()
        self.summaries: list[str] = []
        self.source_chunk_ids: set[str] = set()


class _RelGroup:
    """Accumulator for relationships that share a dedup key."""

    __slots__ = (
        "source_entity_uuid",
        "target_entity_uuid",
        "relationship_name",
        "facts",
        "episode_uuids",
    )

    def __init__(
        self,
        source_entity_uuid: str,
        target_entity_uuid: str,
        relationship_name: str,
    ) -> None:
        self.source_entity_uuid = source_entity_uuid
        self.target_entity_uuid = target_entity_uuid
        self.relationship_name = relationship_name
        self.facts: list[str] = []
        self.episode_uuids: set[str] = set()
