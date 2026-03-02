"""Neo4j bulk writer for the batch import pipeline.

Writes resolved entities, relationships, episodes (chunks), and mention
edges into Neo4j using Graphiti-compatible schema.  All writes use batched
UNWIND statements to avoid transaction-size OOM and to keep throughput high.

The Graphiti schema contract:
- :Episodic  -- one node per chunk (episode)
- :Entity    -- one node per resolved entity, with a dynamic sub-label for entity_type
- :RELATES_TO -- edges between entities carrying a fact + embedding
- :MENTIONS   -- edges from episodes to entities they mention
"""

from __future__ import annotations

import json
import logging
import re
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from knowledge_base.batch.models import ResolvedEntity, ResolvedRelationship
from knowledge_base.config import settings
from knowledge_base.graph.graphiti_client import GraphitiClient

if TYPE_CHECKING:
    from knowledge_base.vectorstore.indexer import ChunkData

logger = logging.getLogger(__name__)

# Regex to sanitise dynamic Neo4j labels -- only allow alphanumeric + underscore.
_SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9_]")


def _sanitize_label(raw: str) -> str:
    """Sanitize a string for safe use as a Neo4j node label.

    Removes all characters that are not alphanumeric or underscore,
    and ensures the result starts with an uppercase letter.
    """
    cleaned = _SAFE_LABEL_RE.sub("", raw)
    if not cleaned:
        return "Entity"
    # Ensure first character is a letter
    if not cleaned[0].isalpha():
        cleaned = "X" + cleaned
    return cleaned[0].upper() + cleaned[1:]


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Neo4jBulkLoader:
    """Bulk-writes resolved graph data into Neo4j using Graphiti-compatible schema.

    All writes are batched via UNWIND to control memory usage and avoid
    Neo4j transaction OOM on large imports.
    """

    def __init__(
        self,
        group_id: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.group_id = group_id or settings.GRAPH_GROUP_ID
        self.batch_size = batch_size or settings.BATCH_NEO4J_WRITE_SIZE
        self._graphiti_client = GraphitiClient()
        logger.info(
            "Neo4jBulkLoader initialised  group_id=%s  batch_size=%d",
            self.group_id,
            self.batch_size,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def clear_graph(self) -> int:
        """Delete ALL nodes (and their relationships) with matching group_id.

        Deletes are executed in batches to avoid Neo4j OOM on large graphs.

        Returns:
            Total number of nodes deleted.
        """
        logger.info("Clearing graph for group_id=%s", self.group_id)
        graphiti = await self._graphiti_client.get_client()
        driver = graphiti.driver

        total_deleted = 0
        while True:
            records, _, _ = await driver.execute_query(
                "MATCH (n {group_id: $group_id}) "
                "WITH n LIMIT $limit "
                "DETACH DELETE n "
                "RETURN count(*) AS deleted",
                params={"group_id": self.group_id, "limit": self.batch_size},
            )
            deleted = records[0]["deleted"] if records else 0
            if deleted == 0:
                break
            total_deleted += deleted
            logger.info(
                "Deleted %d nodes (total so far: %d)", deleted, total_deleted
            )

        logger.info(
            "Graph cleared for group_id=%s  total_deleted=%d",
            self.group_id,
            total_deleted,
        )
        return total_deleted

    async def load_episodes(
        self,
        chunks: list[ChunkData],
        episode_uuids: dict[str, str],
    ) -> None:
        """Create :Episodic nodes in Neo4j for each chunk.

        Args:
            chunks: List of ChunkData objects to create episodes from.
            episode_uuids: Mapping of chunk_id -> episode UUID.
        """
        logger.info("Loading %d episodes into Neo4j", len(chunks))
        now_iso = _utcnow_iso()

        batch: list[dict] = []
        for chunk in chunks:
            ep_uuid = episode_uuids.get(chunk.chunk_id)
            if ep_uuid is None:
                logger.warning(
                    "No episode UUID for chunk_id=%s, skipping", chunk.chunk_id
                )
                continue

            # Build source_description as JSON metadata dict (matches graphiti_builder.py:520)
            metadata_dict = chunk.to_metadata()
            source_description = json.dumps(metadata_dict, default=str)

            valid_at = chunk.updated_at if chunk.updated_at else now_iso

            batch.append(
                {
                    "uuid": ep_uuid,
                    "name": chunk.chunk_id,
                    "group_id": self.group_id,
                    "source": "text",
                    "source_description": source_description,
                    "content": chunk.content,
                    "entity_edges": [],
                    "created_at": now_iso,
                    "valid_at": valid_at,
                }
            )

        query = (
            "UNWIND $batch AS ep "
            "MERGE (e:Episodic {uuid: ep.uuid}) "
            "SET e.name = ep.name, "
            "    e.group_id = ep.group_id, "
            "    e.source = ep.source, "
            "    e.source_description = ep.source_description, "
            "    e.content = ep.content, "
            "    e.entity_edges = ep.entity_edges, "
            "    e.created_at = datetime(ep.created_at), "
            "    e.valid_at = datetime(ep.valid_at)"
        )
        await self._execute_batch(query, batch, label="episodes")

    async def load_entities(self, entities: list[ResolvedEntity]) -> None:
        """Create :Entity nodes with dynamic type sub-labels.

        Entities are grouped by entity_type so that each UNWIND batch
        uses the correct secondary label (e.g. ``Entity:Technology``).

        Args:
            entities: List of resolved entities to write.
        """
        logger.info("Loading %d entities into Neo4j", len(entities))
        now_iso = _utcnow_iso()

        # Group by entity_type for label assignment
        by_type: dict[str, list[dict]] = {}
        for ent in entities:
            safe_label = _sanitize_label(ent.entity_type)
            row = {
                "uuid": ent.uuid,
                "name": ent.canonical_name,
                "group_id": self.group_id,
                "name_embedding": ent.name_embedding or [],
                "summary": ent.summary,
                "created_at": now_iso,
            }
            by_type.setdefault(safe_label, []).append(row)

        for type_label, rows in by_type.items():
            # Cypher does not support parameterized labels, so the label is
            # baked into the query string.  _sanitize_label ensures only safe
            # alphanumeric characters are used (injection-safe).
            query = (
                "UNWIND $batch AS ent "
                f"MERGE (n:Entity:{type_label} {{uuid: ent.uuid}}) "
                "SET n.name = ent.name, "
                "    n.group_id = ent.group_id, "
                "    n.name_embedding = ent.name_embedding, "
                "    n.summary = ent.summary, "
                "    n.created_at = datetime(ent.created_at)"
            )
            await self._execute_batch(
                query, rows, label=f"entities:{type_label}"
            )

    async def load_relationships(
        self, relationships: list[ResolvedRelationship]
    ) -> None:
        """Create :RELATES_TO edges between entity pairs.

        Args:
            relationships: List of resolved relationships to write.
        """
        logger.info("Loading %d relationships into Neo4j", len(relationships))
        now_iso = _utcnow_iso()

        batch: list[dict] = []
        for rel in relationships:
            batch.append(
                {
                    "uuid": rel.uuid,
                    "source_uuid": rel.source_entity_uuid,
                    "target_uuid": rel.target_entity_uuid,
                    "name": rel.relationship_name,
                    "group_id": self.group_id,
                    "fact": rel.fact,
                    "fact_embedding": rel.fact_embedding or [],
                    "episodes": rel.episode_uuids,
                    "created_at": now_iso,
                    "valid_at": now_iso,
                }
            )

        query = (
            "UNWIND $batch AS e "
            "MATCH (src:Entity {uuid: e.source_uuid}) "
            "MATCH (tgt:Entity {uuid: e.target_uuid}) "
            "MERGE (src)-[r:RELATES_TO {uuid: e.uuid}]->(tgt) "
            "SET r.name = e.name, "
            "    r.group_id = e.group_id, "
            "    r.fact = e.fact, "
            "    r.fact_embedding = e.fact_embedding, "
            "    r.episodes = e.episodes, "
            "    r.created_at = datetime(e.created_at), "
            "    r.expired_at = null, "
            "    r.valid_at = datetime(e.valid_at), "
            "    r.invalid_at = null"
        )
        await self._execute_batch(query, batch, label="relationships")

    async def load_mentions(
        self,
        entities: list[ResolvedEntity],
        episode_uuids_all: list[str],
    ) -> None:
        """Create :MENTIONS edges from episodes to entities.

        For each entity, a MENTIONS edge is created from every episode
        in which the entity was mentioned (tracked in
        ``entity.mentioned_in_episodes``).

        Args:
            entities: Resolved entities carrying ``mentioned_in_episodes``.
            episode_uuids_all: All episode UUIDs in the graph (for validation logging).
        """
        logger.info(
            "Loading MENTIONS edges  entities=%d  total_episodes=%d",
            len(entities),
            len(episode_uuids_all),
        )
        now_iso = _utcnow_iso()
        episode_set = set(episode_uuids_all)

        batch: list[dict] = []
        skipped = 0
        for ent in entities:
            for ep_uuid in ent.mentioned_in_episodes:
                if ep_uuid not in episode_set:
                    skipped += 1
                    continue
                batch.append(
                    {
                        "episode_uuid": ep_uuid,
                        "entity_uuid": ent.uuid,
                        "uuid": str(uuid_mod.uuid4()),
                        "group_id": self.group_id,
                        "created_at": now_iso,
                    }
                )

        if skipped:
            logger.warning(
                "Skipped %d MENTIONS edges referencing unknown episode UUIDs",
                skipped,
            )

        query = (
            "UNWIND $batch AS m "
            "MATCH (ep:Episodic {uuid: m.episode_uuid}) "
            "MATCH (ent:Entity {uuid: m.entity_uuid}) "
            "MERGE (ep)-[r:MENTIONS {uuid: m.uuid}]->(ent) "
            "SET r.group_id = m.group_id, "
            "    r.created_at = datetime(m.created_at)"
        )
        await self._execute_batch(query, batch, label="mentions")

    async def update_episode_edge_refs(
        self,
        chunks: list[ChunkData],
        episode_uuids: dict[str, str],
        relationships: list[ResolvedRelationship],
    ) -> None:
        """Populate ``entity_edges`` on Episodic nodes.

        For each episode, collect the UUIDs of all RELATES_TO edges whose
        ``episodes`` list references that episode, then write the list back
        to the Episodic node's ``entity_edges`` property.

        Args:
            chunks: Original chunk list (used for chunk_id -> episode_uuid mapping).
            episode_uuids: Mapping of chunk_id -> episode UUID.
            relationships: All resolved relationships (carry ``episode_uuids``).
        """
        logger.info("Updating entity_edges references on Episodic nodes")

        # Build episode_uuid -> list of relationship UUIDs
        ep_to_edges: dict[str, list[str]] = {}
        for rel in relationships:
            for ep_uuid in rel.episode_uuids:
                ep_to_edges.setdefault(ep_uuid, []).append(rel.uuid)

        batch: list[dict] = []
        for chunk in chunks:
            ep_uuid = episode_uuids.get(chunk.chunk_id)
            if ep_uuid is None:
                continue
            edge_uuids = ep_to_edges.get(ep_uuid, [])
            batch.append({"uuid": ep_uuid, "edge_uuids": edge_uuids})

        query = (
            "UNWIND $batch AS ep "
            "MATCH (e:Episodic {uuid: ep.uuid}) "
            "SET e.entity_edges = ep.edge_uuids"
        )
        await self._execute_batch(query, batch, label="episode_edge_refs")

    async def update_entity_embeddings(
        self, batch: list[tuple[str, list[float]]]
    ) -> None:
        """Update ``name_embedding`` on existing :Entity nodes.

        Used by the streaming embed+load pipeline: entities are loaded first
        without embeddings, then embeddings are computed and written in batches
        to avoid holding all vectors in memory at once.

        Args:
            batch: List of (entity_uuid, embedding_vector) pairs.
        """
        if not batch:
            return
        data = [{"uuid": uid, "embedding": emb} for uid, emb in batch]
        query = (
            "UNWIND $batch AS row "
            "MATCH (n:Entity {uuid: row.uuid}) "
            "SET n.name_embedding = row.embedding"
        )
        await self._execute_batch(query, data, label="entity_embeddings")

    async def update_edge_embeddings(
        self, batch: list[tuple[str, list[float]]]
    ) -> None:
        """Update ``fact_embedding`` on existing :RELATES_TO edges.

        Used by the streaming embed+load pipeline: edges are loaded first
        without embeddings, then embeddings are computed and written in batches.

        Args:
            batch: List of (relationship_uuid, embedding_vector) pairs.
        """
        if not batch:
            return
        data = [{"uuid": uid, "embedding": emb} for uid, emb in batch]
        query = (
            "UNWIND $batch AS row "
            "MATCH ()-[r:RELATES_TO {uuid: row.uuid}]-() "
            "SET r.fact_embedding = row.embedding"
        )
        await self._execute_batch(query, data, label="edge_embeddings")

    async def build_indices(self) -> None:
        """Create all indices required by Graphiti search.

        Creates range + fulltext indices via Graphiti, then adds HNSW vector
        indices for fast similarity search (Graphiti doesn't create these).
        """
        from knowledge_base.graph.vector_indices import create_vector_indices

        logger.info("Building Neo4j indices and constraints via Graphiti")
        graphiti = await self._graphiti_client.get_client()
        await graphiti.build_indices_and_constraints()

        # Create HNSW vector indices (not created by Graphiti)
        logger.info("Creating HNSW vector indices")
        await create_vector_indices(graphiti.driver)

        logger.info("Neo4j indices and constraints created successfully (including HNSW vector)")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _execute_batch(
        self,
        query: str,
        data: list[dict],
        label: str = "items",
    ) -> None:
        """Execute a Cypher UNWIND query in batches of ``self.batch_size``.

        Args:
            query: Cypher query containing ``UNWIND $batch AS ...``.
            data: Full list of parameter dicts to partition into batches.
            label: Human-readable label for log messages.
        """
        if not data:
            logger.info("No %s to write, skipping", label)
            return

        total = len(data)
        graphiti = await self._graphiti_client.get_client()
        driver = graphiti.driver

        written = 0
        for start in range(0, total, self.batch_size):
            chunk = data[start : start + self.batch_size]
            await driver.execute_query(query, params={"batch": chunk})
            written += len(chunk)
            logger.info(
                "Wrote %d / %d %s  (batch %d-%d)",
                written,
                total,
                label,
                start,
                start + len(chunk) - 1,
            )

        logger.info("Finished writing %d %s", total, label)
