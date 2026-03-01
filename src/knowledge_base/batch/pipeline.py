"""Batch import pipeline orchestrator.

Coordinates the full batch import flow: episode creation, LLM extraction
via Gemini Batch API, entity resolution, and streaming embed+load into Neo4j.
Supports resume from any phase via GCS-persisted state.

Phases:
    1. FETCH    -- count and log incoming chunks (already provided by caller)
    2. EPISODES -- generate episode UUIDs, optionally clear graph, load episodes
    3. EXTRACT  -- prepare JSONL, submit Gemini Batch API job, poll, parse
    4. RESOLVE  -- deterministic entity/relationship deduplication
    5. LOAD     -- streaming embed+load: write nodes/edges to Neo4j, then
                   stream embeddings in batches (only one batch in memory at
                   a time, ~60 KB, safe for 100K+ entities in 8 Gi)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from google.cloud import storage as gcs

from knowledge_base.batch.embedder import BatchEmbedder
from knowledge_base.batch.extractor import BatchExtractor
from knowledge_base.batch.loader import Neo4jBulkLoader
from knowledge_base.batch.models import BatchImportState, ResolvedEntity, ResolvedRelationship
from knowledge_base.batch.resolver import EntityResolver
from knowledge_base.config import Settings, settings
from knowledge_base.vectorstore.indexer import ChunkData

logger = logging.getLogger(__name__)

# Ordered list of phases for comparison (earlier index = earlier phase).
_PHASE_ORDER = [
    "prepare",
    "episodes",
    "submitted",
    "extracted",
    "resolved",
    # "embedded" removed -- embed+load are now a single streaming phase
    "complete",
]


def _phase_done(current: str, target: str) -> bool:
    """Return True if *current* phase is at or past *target*."""
    try:
        return _PHASE_ORDER.index(current) >= _PHASE_ORDER.index(target)
    except ValueError:
        # Handle legacy "embedded" phase from prior runs -- treat as "resolved"
        if current == "embedded":
            try:
                return _PHASE_ORDER.index("resolved") >= _PHASE_ORDER.index(target)
            except ValueError:
                return False
        return False


class BatchImportPipeline:
    """Orchestrates the full batch import pipeline with GCS-backed resume.

    Usage::

        pipeline = BatchImportPipeline()
        summary = await pipeline.run(chunks, resume=False, clear_graph=True)
    """

    def __init__(self, app_settings: Settings | None = None) -> None:
        self._settings = app_settings or settings

        # Component instances
        self._extractor = BatchExtractor(self._settings)
        self._resolver = EntityResolver()
        self._embedder = BatchEmbedder()
        self._loader = Neo4jBulkLoader()

        # GCS state persistence
        self._gcs_client = gcs.Client(project=self._settings.GCP_PROJECT_ID)
        self._state_key = f"{self._settings.BATCH_GCS_PREFIX}/state.json"
        self._episode_uuids_key = f"{self._settings.BATCH_GCS_PREFIX}/episode_uuids.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        chunks: list[ChunkData],
        resume: bool = False,
        clear_graph: bool = False,
        dry_run: bool = False,
    ) -> dict:
        """Execute the full batch import pipeline.

        Parameters
        ----------
        chunks
            Document chunks to import into the knowledge graph.
        resume
            If True, load state from GCS and skip already-completed phases.
        clear_graph
            If True, delete all existing nodes for the group before loading episodes.
        dry_run
            If True, prepare JSONL input and log a sample but do not submit
            the batch job or write to Neo4j.

        Returns
        -------
        dict
            Summary with counts of chunks, entities, relationships, etc.
        """
        pipeline_start = time.monotonic()
        state: BatchImportState | None = None
        episode_uuids: dict[str, str] = {}

        # Resume: load prior state
        if resume:
            state = self._load_state()
            if state is not None:
                logger.info(
                    "Resuming from phase=%s  batch_job=%s  chunks_total=%d",
                    state.phase,
                    state.batch_job_name or "(none)",
                    state.chunks_total,
                )
                episode_uuids = self._load_episode_uuids()
            else:
                logger.info("No prior state found in GCS -- starting fresh")

        current_phase = state.phase if state else ""

        # ------------------------------------------------------------------
        # Phase 1: FETCH (just count and log)
        # ------------------------------------------------------------------
        logger.info(
            "Phase 1/5 FETCH: received %d chunks for import", len(chunks)
        )

        # ------------------------------------------------------------------
        # Phase 2: EPISODES
        # ------------------------------------------------------------------
        if not _phase_done(current_phase, "episodes"):
            logger.info("Phase 2/5 EPISODES: generating UUIDs and loading into Neo4j")

            episode_uuids = {
                chunk.chunk_id: str(uuid4()) for chunk in chunks
            }

            if clear_graph:
                logger.info("clear_graph=True -- deleting existing graph data")
                deleted = await self._loader.clear_graph()
                logger.info("Cleared %d nodes from graph", deleted)

            await self._loader.load_episodes(chunks, episode_uuids)
            logger.info(
                "Loaded %d episodes into Neo4j", len(episode_uuids)
            )

            # Persist episode UUIDs (needed across phases for resume)
            self._save_episode_uuids(episode_uuids)

            self._save_state(BatchImportState(
                phase="episodes",
                chunks_total=len(chunks),
                timestamp=_utcnow_iso(),
            ))
        else:
            logger.info("Phase 2/5 EPISODES: already completed -- skipping")

        # ------------------------------------------------------------------
        # Phase 3: EXTRACT (Gemini Batch API)
        # ------------------------------------------------------------------
        extractions: dict = {}
        # Track output_dir and job_name as locals so they survive across phases
        batch_job_name = state.batch_job_name if state else None
        output_dir = state.output_dir if state else None

        if not _phase_done(current_phase, "extracted"):
            logger.info(
                "Phase 3/5 EXTRACT: preparing JSONL for %d chunks", len(chunks)
            )

            # Step 3a: prepare JSONL (always needed, even for resume at 'submitted')
            if not _phase_done(current_phase, "submitted"):
                input_uri = self._extractor.prepare_jsonl(chunks)

                if dry_run:
                    logger.info(
                        "DRY RUN: JSONL uploaded to %s -- stopping before batch submission",
                        input_uri,
                    )
                    return {
                        "dry_run": True,
                        "chunks_total": len(chunks),
                        "input_uri": input_uri,
                        "episode_uuids": len(episode_uuids),
                    }

                # Step 3b: submit batch job
                batch_job_name = self._extractor.submit_batch(input_uri)
                logger.info("Batch job submitted: %s", batch_job_name)

                self._save_state(BatchImportState(
                    phase="submitted",
                    batch_job_name=batch_job_name,
                    input_uri=input_uri,
                    chunks_total=len(chunks),
                    timestamp=_utcnow_iso(),
                ))
            else:
                # Resuming from 'submitted' -- reuse stored job name
                if not batch_job_name:
                    raise RuntimeError(
                        "Cannot resume from 'submitted' phase without a stored batch_job_name"
                    )
                logger.info("Resuming poll for batch job: %s", batch_job_name)

            # Step 3c: poll until complete
            output_dir = self._extractor.poll_until_complete(batch_job_name)
            logger.info("Batch job completed, output at: %s", output_dir)

            # Step 3d: parse results
            extractions = self._extractor.parse_results(output_dir)
            logger.info(
                "Parsed %d extraction results from batch output",
                len(extractions),
            )

            self._save_state(BatchImportState(
                phase="extracted",
                batch_job_name=batch_job_name,
                output_dir=output_dir,
                chunks_total=len(chunks),
                timestamp=_utcnow_iso(),
            ))
        else:
            logger.info("Phase 3/5 EXTRACT: already completed -- skipping")
            # Re-parse results from stored output directory for downstream phases
            if output_dir:
                logger.info(
                    "Re-downloading extraction results from %s", output_dir
                )
                extractions = self._extractor.parse_results(output_dir)
                logger.info(
                    "Re-parsed %d extraction results", len(extractions)
                )
            else:
                raise RuntimeError(
                    "Cannot resume past 'extracted' phase without a stored output_dir"
                )

        # ------------------------------------------------------------------
        # Phase 4: RESOLVE
        # ------------------------------------------------------------------
        entities: list[ResolvedEntity] = []
        relationships: list[ResolvedRelationship] = []

        if not _phase_done(current_phase, "resolved"):
            logger.info("Phase 4/5 RESOLVE: deduplicating entities and relationships")

            entities, relationships = self._resolver.resolve(
                extractions, episode_uuids
            )
            logger.info(
                "Resolved %d unique entities, %d relationships",
                len(entities),
                len(relationships),
            )

            self._save_state(BatchImportState(
                phase="resolved",
                batch_job_name=batch_job_name,
                output_dir=output_dir,
                chunks_total=len(chunks),
                timestamp=_utcnow_iso(),
            ))
        else:
            logger.info(
                "Phase 4/5 RESOLVE: already completed -- re-resolving from extractions"
            )
            entities, relationships = self._resolver.resolve(
                extractions, episode_uuids
            )
            logger.info(
                "Re-resolved %d entities, %d relationships",
                len(entities),
                len(relationships),
            )

        # ------------------------------------------------------------------
        # Phase 5: LOAD (streaming embed + load)
        # ------------------------------------------------------------------
        if not _phase_done(current_phase, "complete"):
            logger.info(
                "Phase 5/5 LOAD: streaming embed+load for %d entities, %d relationships",
                len(entities),
                len(relationships),
            )

            # Step 5a: Load entities into Neo4j WITHOUT embeddings
            logger.info("Step 5a: Loading %d entities into Neo4j (no embeddings yet)", len(entities))
            await self._loader.load_entities(entities)

            # Step 5b: Stream entity name embeddings -> update in Neo4j
            logger.info("Step 5b: Streaming entity name embeddings to Neo4j")
            embedded_entities = await self._embedder.stream_embed_entities(
                entities, self._loader.update_entity_embeddings
            )
            logger.info("Embedded %d/%d entity names", embedded_entities, len(entities))

            # Step 5c: Load relationships into Neo4j WITHOUT embeddings
            logger.info("Step 5c: Loading %d relationships into Neo4j (no embeddings yet)", len(relationships))
            await self._loader.load_relationships(relationships)

            # Step 5d: Stream edge fact embeddings -> update in Neo4j
            logger.info("Step 5d: Streaming edge fact embeddings to Neo4j")
            embedded_edges = await self._embedder.stream_embed_edges(
                relationships, self._loader.update_edge_embeddings
            )
            logger.info("Embedded %d/%d edge facts", embedded_edges, len(relationships))

            # Step 5e: Load MENTIONS edges and episode references
            logger.info("Step 5e: Loading MENTIONS edges and episode references")
            await self._loader.load_mentions(
                entities, list(episode_uuids.values())
            )
            await self._loader.update_episode_edge_refs(
                chunks, episode_uuids, relationships
            )

            # Step 5f: Build indices
            logger.info("Step 5f: Building Neo4j indices")
            await self._loader.build_indices()

            self._save_state(BatchImportState(
                phase="complete",
                batch_job_name=batch_job_name,
                output_dir=output_dir,
                chunks_total=len(chunks),
                timestamp=_utcnow_iso(),
            ))

            logger.info("Phase 5/5 LOAD: complete")
        else:
            logger.info("Phase 5/5 LOAD: already completed -- nothing to do")

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        elapsed = time.monotonic() - pipeline_start
        total_mentions = sum(
            len(e.mentioned_in_episodes) for e in entities
        )

        summary = {
            "chunks_total": len(chunks),
            "episodes_created": len(episode_uuids),
            "extractions_parsed": len(extractions),
            "entities_resolved": len(entities),
            "relationships_resolved": len(relationships),
            "mentions_created": total_mentions,
            "elapsed_seconds": round(elapsed, 1),
        }

        logger.info(
            "Pipeline complete in %.1fs: %d chunks -> %d entities, "
            "%d relationships, %d mentions",
            elapsed,
            len(chunks),
            len(entities),
            len(relationships),
            total_mentions,
        )

        return summary

    # ------------------------------------------------------------------
    # GCS state persistence
    # ------------------------------------------------------------------

    def _save_state(self, state: BatchImportState) -> None:
        """Serialize pipeline state to JSON and upload to GCS."""
        bucket = self._gcs_client.bucket(self._settings.BATCH_GCS_BUCKET)
        blob = bucket.blob(self._state_key)
        payload = state.model_dump_json(indent=2)
        blob.upload_from_string(payload, content_type="application/json")
        logger.debug("Saved pipeline state: phase=%s -> %s", state.phase, self._state_key)

    def _load_state(self) -> BatchImportState | None:
        """Download and deserialize pipeline state from GCS.

        Returns None if no state file exists.
        """
        bucket = self._gcs_client.bucket(self._settings.BATCH_GCS_BUCKET)
        blob = bucket.blob(self._state_key)

        if not blob.exists():
            logger.debug("No state file found at %s", self._state_key)
            return None

        payload = blob.download_as_text(encoding="utf-8")
        state = BatchImportState.model_validate_json(payload)
        logger.debug("Loaded pipeline state: phase=%s", state.phase)
        return state

    def _save_episode_uuids(self, episode_uuids: dict[str, str]) -> None:
        """Persist episode UUID mapping to GCS for cross-phase resume."""
        bucket = self._gcs_client.bucket(self._settings.BATCH_GCS_BUCKET)
        blob = bucket.blob(self._episode_uuids_key)
        payload = json.dumps(episode_uuids, indent=2)
        blob.upload_from_string(payload, content_type="application/json")
        logger.debug(
            "Saved %d episode UUIDs to %s",
            len(episode_uuids),
            self._episode_uuids_key,
        )

    def _load_episode_uuids(self) -> dict[str, str]:
        """Load episode UUID mapping from GCS.

        Returns an empty dict if the file does not exist.
        """
        bucket = self._gcs_client.bucket(self._settings.BATCH_GCS_BUCKET)
        blob = bucket.blob(self._episode_uuids_key)

        if not blob.exists():
            logger.warning(
                "No episode UUIDs file found at %s -- returning empty mapping",
                self._episode_uuids_key,
            )
            return {}

        payload = blob.download_as_text(encoding="utf-8")
        uuids: dict[str, str] = json.loads(payload)
        logger.debug(
            "Loaded %d episode UUIDs from %s",
            len(uuids),
            self._episode_uuids_key,
        )
        return uuids


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
