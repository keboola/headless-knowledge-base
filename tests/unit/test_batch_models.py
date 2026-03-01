"""Tests for batch import pipeline models."""

import json

import pytest

from knowledge_base.batch.models import (
    BatchImportState,
    ChunkExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    ResolvedEntity,
    ResolvedRelationship,
)


# ---------------------------------------------------------------------------
# ExtractedEntity
# ---------------------------------------------------------------------------


class TestExtractedEntity:
    """Tests for ExtractedEntity model."""

    def test_creation(self) -> None:
        entity = ExtractedEntity(
            name="Platform Team",
            entity_type="Team",
            summary="The Platform Team manages infrastructure.",
        )
        assert entity.name == "Platform Team"
        assert entity.entity_type == "Team"
        assert entity.summary == "The Platform Team manages infrastructure."

    def test_requires_all_fields(self) -> None:
        with pytest.raises(Exception):
            ExtractedEntity(name="Test")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ExtractedRelationship
# ---------------------------------------------------------------------------


class TestExtractedRelationship:
    """Tests for ExtractedRelationship model."""

    def test_creation(self) -> None:
        rel = ExtractedRelationship(
            source_entity="Platform Team",
            target_entity="CI/CD Pipeline",
            relationship_name="manages",
            fact="The Platform Team manages the CI/CD pipeline.",
        )
        assert rel.source_entity == "Platform Team"
        assert rel.target_entity == "CI/CD Pipeline"
        assert rel.relationship_name == "manages"
        assert rel.fact == "The Platform Team manages the CI/CD pipeline."


# ---------------------------------------------------------------------------
# ChunkExtractionResult
# ---------------------------------------------------------------------------


class TestChunkExtractionResult:
    """Tests for ChunkExtractionResult model."""

    def test_creation_with_entities_and_relationships(self) -> None:
        result = ChunkExtractionResult(
            entities=[
                ExtractedEntity(
                    name="Alice",
                    entity_type="Person",
                    summary="Alice is an engineer.",
                )
            ],
            relationships=[
                ExtractedRelationship(
                    source_entity="Alice",
                    target_entity="Platform Team",
                    relationship_name="member_of",
                    fact="Alice is a member of the Platform Team.",
                )
            ],
            summary="This chunk describes Alice and her team.",
        )
        assert len(result.entities) == 1
        assert len(result.relationships) == 1
        assert result.summary == "This chunk describes Alice and her team."

    def test_creation_with_defaults(self) -> None:
        """entities and relationships default to empty lists."""
        result = ChunkExtractionResult(summary="A summary.")
        assert result.entities == []
        assert result.relationships == []
        assert result.summary == "A summary."

    def test_extraction_json_schema_returns_dict(self) -> None:
        schema = ChunkExtractionResult.extraction_json_schema()
        assert isinstance(schema, dict)

    def test_extraction_json_schema_is_valid_object_type(self) -> None:
        schema = ChunkExtractionResult.extraction_json_schema()
        assert schema["type"] == "object"

    def test_extraction_json_schema_has_required_fields(self) -> None:
        schema = ChunkExtractionResult.extraction_json_schema()
        required = schema["required"]
        assert "entities" in required
        assert "relationships" in required
        assert "summary" in required

    def test_extraction_json_schema_entities_is_array(self) -> None:
        schema = ChunkExtractionResult.extraction_json_schema()
        entities_schema = schema["properties"]["entities"]
        assert entities_schema["type"] == "array"

    def test_extraction_json_schema_relationships_is_array(self) -> None:
        schema = ChunkExtractionResult.extraction_json_schema()
        rels_schema = schema["properties"]["relationships"]
        assert rels_schema["type"] == "array"

    def test_extraction_json_schema_summary_is_string(self) -> None:
        schema = ChunkExtractionResult.extraction_json_schema()
        assert schema["properties"]["summary"]["type"] == "string"

    def test_extraction_json_schema_uses_only_simple_types(self) -> None:
        """Gemini Batch API requires simple types: object, array, string."""
        schema = ChunkExtractionResult.extraction_json_schema()
        allowed_types = {"object", "array", "string"}

        def _check_types(node: dict) -> None:
            if "type" in node:
                assert node["type"] in allowed_types, (
                    f"Found disallowed type '{node['type']}' -- "
                    f"Gemini schema only supports {allowed_types}"
                )
            if "properties" in node:
                for prop in node["properties"].values():
                    _check_types(prop)
            if "items" in node and isinstance(node["items"], dict):
                _check_types(node["items"])

        _check_types(schema)

    def test_extraction_json_schema_entity_required_fields(self) -> None:
        schema = ChunkExtractionResult.extraction_json_schema()
        entity_item = schema["properties"]["entities"]["items"]
        assert set(entity_item["required"]) == {"name", "entity_type", "summary"}

    def test_extraction_json_schema_relationship_required_fields(self) -> None:
        schema = ChunkExtractionResult.extraction_json_schema()
        rel_item = schema["properties"]["relationships"]["items"]
        assert set(rel_item["required"]) == {
            "source_entity",
            "target_entity",
            "relationship_name",
            "fact",
        }

    def test_extraction_json_schema_no_pydantic_keys(self) -> None:
        """Schema must not contain Pydantic-specific keys that Gemini rejects."""
        schema_str = json.dumps(ChunkExtractionResult.extraction_json_schema())
        for forbidden in ["$defs", "title", "anyOf", "allOf", "oneOf"]:
            assert forbidden not in schema_str, (
                f"Found Pydantic key '{forbidden}' in schema -- "
                f"Gemini Batch API does not accept these"
            )


# ---------------------------------------------------------------------------
# ResolvedEntity
# ---------------------------------------------------------------------------


class TestResolvedEntity:
    """Tests for ResolvedEntity model."""

    def test_creation_with_required_fields(self) -> None:
        entity = ResolvedEntity(
            uuid="ent-123",
            canonical_name="Platform Team",
            entity_type="Team",
            summary="The Platform Team owns infrastructure.",
        )
        assert entity.uuid == "ent-123"
        assert entity.canonical_name == "Platform Team"
        assert entity.entity_type == "Team"
        assert entity.summary == "The Platform Team owns infrastructure."

    def test_defaults(self) -> None:
        entity = ResolvedEntity(
            uuid="ent-1",
            canonical_name="X",
            entity_type="Concept",
            summary="A concept.",
        )
        assert entity.name_embedding is None
        assert entity.mentioned_in_episodes == []
        assert entity.raw_names == set()

    def test_raw_names_is_set(self) -> None:
        entity = ResolvedEntity(
            uuid="ent-1",
            canonical_name="X",
            entity_type="Concept",
            summary="A concept.",
            raw_names={"X", "x", "  x  "},
        )
        assert isinstance(entity.raw_names, set)
        assert len(entity.raw_names) == 3


# ---------------------------------------------------------------------------
# ResolvedRelationship
# ---------------------------------------------------------------------------


class TestResolvedRelationship:
    """Tests for ResolvedRelationship model."""

    def test_creation_with_required_fields(self) -> None:
        rel = ResolvedRelationship(
            uuid="rel-1",
            source_entity_uuid="ent-1",
            target_entity_uuid="ent-2",
            relationship_name="manages",
            fact="Entity 1 manages Entity 2.",
        )
        assert rel.uuid == "rel-1"
        assert rel.source_entity_uuid == "ent-1"
        assert rel.target_entity_uuid == "ent-2"
        assert rel.relationship_name == "manages"
        assert rel.fact == "Entity 1 manages Entity 2."

    def test_defaults(self) -> None:
        rel = ResolvedRelationship(
            uuid="rel-1",
            source_entity_uuid="ent-1",
            target_entity_uuid="ent-2",
            relationship_name="manages",
            fact="A fact.",
        )
        assert rel.fact_embedding is None
        assert rel.episode_uuids == []


# ---------------------------------------------------------------------------
# BatchImportState
# ---------------------------------------------------------------------------


class TestBatchImportState:
    """Tests for BatchImportState model."""

    def test_creation(self) -> None:
        state = BatchImportState(
            phase="extract",
            timestamp="2026-03-01T12:00:00Z",
        )
        assert state.phase == "extract"
        assert state.timestamp == "2026-03-01T12:00:00Z"
        assert state.batch_job_name is None
        assert state.input_uri is None
        assert state.output_dir is None
        assert state.chunks_total == 0
        assert state.error is None

    def test_serialization_round_trip(self) -> None:
        state = BatchImportState(
            phase="poll",
            batch_job_name="projects/my-project/locations/us-central1/batchJobs/123",
            input_uri="gs://bucket/prefix/input.jsonl",
            output_dir="gs://bucket/prefix/output/",
            chunks_total=1500,
            timestamp="2026-03-01T12:34:56Z",
            error=None,
        )

        json_str = state.model_dump_json()
        restored = BatchImportState.model_validate_json(json_str)

        assert restored.phase == state.phase
        assert restored.batch_job_name == state.batch_job_name
        assert restored.input_uri == state.input_uri
        assert restored.output_dir == state.output_dir
        assert restored.chunks_total == state.chunks_total
        assert restored.timestamp == state.timestamp
        assert restored.error == state.error

    def test_serialization_with_error(self) -> None:
        state = BatchImportState(
            phase="extract",
            timestamp="2026-03-01T12:00:00Z",
            error="Something went wrong",
        )
        json_str = state.model_dump_json()
        restored = BatchImportState.model_validate_json(json_str)
        assert restored.error == "Something went wrong"

    def test_json_is_valid_json(self) -> None:
        state = BatchImportState(
            phase="done",
            timestamp="2026-03-01T00:00:00Z",
        )
        parsed = json.loads(state.model_dump_json())
        assert parsed["phase"] == "done"
