"""Pydantic models for the batch import pipeline.

Defines three categories of models:
1. Extraction schemas -- structured output for Gemini Batch API (one LLM call per chunk).
2. Resolved models -- post entity-resolution, with UUIDs and embeddings for Neo4j import.
3. Pipeline state -- checkpoint for resume capability across pipeline phases.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. Extraction schema models (Gemini Batch API structured output)
# ---------------------------------------------------------------------------

ENTITY_TYPE_GUIDANCE = (
    "One of: Person, Team, Technology, Process, Document, Concept, Location, Organization. "
    "Use the most specific type that applies."
)


class ExtractedEntity(BaseModel):
    """A single entity extracted from a document chunk by the LLM."""

    name: str = Field(
        ...,
        description="Canonical name of the entity as it appears in the text.",
    )
    entity_type: str = Field(
        ...,
        description=ENTITY_TYPE_GUIDANCE,
    )
    summary: str = Field(
        ...,
        description=(
            "One-sentence summary of who or what this entity is, "
            "based on context in the chunk."
        ),
    )


class ExtractedRelationship(BaseModel):
    """A directed relationship between two entities extracted from a chunk."""

    source_entity: str = Field(
        ...,
        description="Name of the source entity (must match an entity name from the same chunk).",
    )
    target_entity: str = Field(
        ...,
        description="Name of the target entity (must match an entity name from the same chunk).",
    )
    relationship_name: str = Field(
        ...,
        description=(
            "Short verb-phrase describing the relationship, e.g. "
            "'manages', 'depends_on', 'authored', 'located_in'."
        ),
    )
    fact: str = Field(
        ...,
        description=(
            "One-sentence factual statement expressing this relationship, "
            "grounded in the chunk text."
        ),
    )


class ChunkExtractionResult(BaseModel):
    """Complete extraction output for a single document chunk.

    This is the schema passed to Gemini Batch API via ``response_schema``
    so that every chunk produces structured JSON with entities,
    relationships, and a summary.
    """

    entities: list[ExtractedEntity] = Field(
        default_factory=list,
        description="All named entities found in the chunk.",
    )
    relationships: list[ExtractedRelationship] = Field(
        default_factory=list,
        description="All relationships between entities found in the chunk.",
    )
    summary: str = Field(
        ...,
        description=(
            "A concise two-to-three sentence summary of the chunk content, "
            "capturing the main topic and key facts."
        ),
    )

    @staticmethod
    def extraction_json_schema() -> dict:
        """Return a JSON Schema dict compatible with Gemini ``response_schema``.

        Gemini Batch API expects a plain JSON Schema using simple types
        (object, array, string) with ``description`` fields for guidance.
        This is NOT the Pydantic ``model_json_schema()`` output -- it omits
        Pydantic-specific keys like ``$defs``, ``title``, and ``anyOf`` that
        the Gemini API does not accept.
        """
        return {
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "description": "All named entities found in the chunk.",
                    "items": {
                        "type": "object",
                        "description": "A single entity extracted from the text.",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": (
                                    "Canonical name of the entity as it appears in the text."
                                ),
                            },
                            "entity_type": {
                                "type": "string",
                                "description": ENTITY_TYPE_GUIDANCE,
                            },
                            "summary": {
                                "type": "string",
                                "description": (
                                    "One-sentence summary of who or what this entity is, "
                                    "based on context in the chunk."
                                ),
                            },
                        },
                        "required": ["name", "entity_type", "summary"],
                    },
                },
                "relationships": {
                    "type": "array",
                    "description": "All relationships between entities found in the chunk.",
                    "items": {
                        "type": "object",
                        "description": (
                            "A directed relationship between two entities in this chunk."
                        ),
                        "properties": {
                            "source_entity": {
                                "type": "string",
                                "description": (
                                    "Name of the source entity "
                                    "(must match an entity name from the same chunk)."
                                ),
                            },
                            "target_entity": {
                                "type": "string",
                                "description": (
                                    "Name of the target entity "
                                    "(must match an entity name from the same chunk)."
                                ),
                            },
                            "relationship_name": {
                                "type": "string",
                                "description": (
                                    "Short verb-phrase describing the relationship, e.g. "
                                    "'manages', 'depends_on', 'authored', 'located_in'."
                                ),
                            },
                            "fact": {
                                "type": "string",
                                "description": (
                                    "One-sentence factual statement expressing this "
                                    "relationship, grounded in the chunk text."
                                ),
                            },
                        },
                        "required": [
                            "source_entity",
                            "target_entity",
                            "relationship_name",
                            "fact",
                        ],
                    },
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "A concise two-to-three sentence summary of the chunk content, "
                        "capturing the main topic and key facts."
                    ),
                },
            },
            "required": ["entities", "relationships", "summary"],
        }


# ---------------------------------------------------------------------------
# 2. Resolved models (post entity-resolution, ready for Neo4j import)
# ---------------------------------------------------------------------------


class ResolvedEntity(BaseModel):
    """An entity after resolution: deduplicated, assigned a UUID, optionally embedded."""

    uuid: str = Field(
        ...,
        description="Globally unique identifier for this resolved entity.",
    )
    canonical_name: str = Field(
        ...,
        description="The chosen canonical name after deduplication.",
    )
    entity_type: str = Field(
        ...,
        description=ENTITY_TYPE_GUIDANCE,
    )
    summary: str = Field(
        ...,
        description="Merged summary describing the entity across all mentions.",
    )
    name_embedding: list[float] | None = Field(
        default=None,
        description="Embedding vector of the canonical name (768-dim text-embedding-005).",
    )
    mentioned_in_episodes: list[str] = Field(
        default_factory=list,
        description="List of episode (chunk) UUIDs where this entity was mentioned.",
    )
    raw_names: set[str] = Field(
        default_factory=set,
        description="All surface-form name variants that resolved to this entity.",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "uuid": "ent-a1b2c3d4",
            "canonical_name": "Platform Team",
            "entity_type": "Team",
            "summary": "The Platform Team owns internal infrastructure and developer tools.",
            "name_embedding": None,
            "mentioned_in_episodes": ["ep-001", "ep-042"],
            "raw_names": ["Platform Team", "platform team", "Platform"],
        }
    }}


class ResolvedRelationship(BaseModel):
    """A relationship after resolution: linked to resolved entity UUIDs, optionally embedded."""

    uuid: str = Field(
        ...,
        description="Globally unique identifier for this resolved relationship.",
    )
    source_entity_uuid: str = Field(
        ...,
        description="UUID of the resolved source entity.",
    )
    target_entity_uuid: str = Field(
        ...,
        description="UUID of the resolved target entity.",
    )
    relationship_name: str = Field(
        ...,
        description="Verb-phrase describing the relationship.",
    )
    fact: str = Field(
        ...,
        description="Factual statement expressing this relationship.",
    )
    fact_embedding: list[float] | None = Field(
        default=None,
        description="Embedding vector of the fact sentence (768-dim text-embedding-005).",
    )
    episode_uuids: list[str] = Field(
        default_factory=list,
        description="List of episode (chunk) UUIDs where this relationship was observed.",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "uuid": "rel-x9y8z7",
            "source_entity_uuid": "ent-a1b2c3d4",
            "target_entity_uuid": "ent-e5f6g7h8",
            "relationship_name": "manages",
            "fact": "The Platform Team manages the internal CI/CD pipeline.",
            "fact_embedding": None,
            "episode_uuids": ["ep-001"],
        }
    }}


# ---------------------------------------------------------------------------
# 3. Pipeline state model (resume checkpoint)
# ---------------------------------------------------------------------------


class BatchImportState(BaseModel):
    """Checkpoint of the batch import pipeline for resume capability.

    Persisted to GCS (JSON) after each phase transition so the pipeline
    can pick up where it left off after a crash or timeout.
    """

    phase: str = Field(
        ...,
        description=(
            "Current pipeline phase: 'prepare', 'extract', 'poll', "
            "'resolve', 'embed', 'load', 'done'."
        ),
    )
    batch_job_name: str | None = Field(
        default=None,
        description="Gemini Batch API job resource name (set after submission).",
    )
    input_uri: str | None = Field(
        default=None,
        description="GCS URI of the JSONL input file sent to Gemini Batch API.",
    )
    output_dir: str | None = Field(
        default=None,
        description="GCS URI prefix where Gemini Batch API wrote output JSONL.",
    )
    chunks_total: int = Field(
        default=0,
        description="Total number of chunks submitted for extraction.",
    )
    timestamp: str = Field(
        ...,
        description="ISO-8601 timestamp of the last state update.",
    )
    error: str | None = Field(
        default=None,
        description="Error message if the pipeline failed (None when healthy).",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "phase": "poll",
            "batch_job_name": "projects/ai-knowledge-base-42/locations/us-central1/batchJobs/123",
            "input_uri": "gs://kb-batch-import/jobs/2026-03-01/input.jsonl",
            "output_dir": "gs://kb-batch-import/jobs/2026-03-01/output/",
            "chunks_total": 1500,
            "timestamp": "2026-03-01T12:34:56Z",
            "error": None,
        }
    }}
