"""Tests for batch import pipeline entity resolver."""

from unittest.mock import patch

import pytest

from knowledge_base.batch.models import (
    ChunkExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    ResolvedEntity,
    ResolvedRelationship,
)
from knowledge_base.batch.resolver import EntityResolver, _normalize_name


# ---------------------------------------------------------------------------
# _normalize_name tests
# ---------------------------------------------------------------------------


class TestNormalizeName:
    """Tests for the _normalize_name utility function."""

    def test_lowercase(self) -> None:
        assert _normalize_name("Platform Team") == "platform team"

    def test_strip_whitespace(self) -> None:
        assert _normalize_name("  Alice  ") == "alice"

    def test_collapse_spaces(self) -> None:
        assert _normalize_name("Platform   Team") == "platform team"

    def test_collapse_mixed_whitespace(self) -> None:
        assert _normalize_name("Platform\t\n Team") == "platform team"

    def test_empty_string(self) -> None:
        assert _normalize_name("") == ""

    def test_already_normalized(self) -> None:
        assert _normalize_name("alice") == "alice"


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def resolver():
    """Create an EntityResolver with default similarity threshold."""
    with patch("knowledge_base.batch.resolver.settings") as mock_settings:
        mock_settings.BATCH_ENTITY_SIMILARITY_THRESHOLD = 0.85
        mock_settings.BATCH_ENTITY_FUZZY_MERGE_ENABLED = False
        yield EntityResolver()


def _make_extraction(
    entities: list[tuple[str, str, str]],
    relationships: list[tuple[str, str, str, str]] | None = None,
    summary: str = "Test summary.",
) -> ChunkExtractionResult:
    """Build a ChunkExtractionResult from simple tuples.

    entities: list of (name, entity_type, summary)
    relationships: list of (source, target, rel_name, fact)
    """
    return ChunkExtractionResult(
        entities=[
            ExtractedEntity(name=n, entity_type=t, summary=s)
            for n, t, s in entities
        ],
        relationships=[
            ExtractedRelationship(
                source_entity=src,
                target_entity=tgt,
                relationship_name=rn,
                fact=f,
            )
            for src, tgt, rn, f in (relationships or [])
        ],
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Entity grouping and deduplication
# ---------------------------------------------------------------------------


class TestEntityDeduplication:
    """Tests for entity normalization and exact-match deduplication."""

    @pytest.mark.asyncio
    async def test_exact_match_deduplication(self, resolver: EntityResolver) -> None:
        """Same normalized name + type across chunks -> one entity."""
        extractions = {
            "chunk-1": _make_extraction([
                ("Platform Team", "Team", "Owns infrastructure."),
            ]),
            "chunk-2": _make_extraction([
                ("platform team", "Team", "Manages CI/CD."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1", "chunk-2": "ep-2"}

        entities, _ = await resolver.resolve(extractions, episode_uuids)

        assert len(entities) == 1
        assert entities[0].canonical_name in ("Platform Team", "platform team")

    @pytest.mark.asyncio
    async def test_different_types_remain_separate(self, resolver: EntityResolver) -> None:
        """Same name but different entity_type -> separate entities."""
        extractions = {
            "chunk-1": _make_extraction([
                ("Mercury", "Technology", "A messaging system."),
                ("Mercury", "Person", "A team member."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        entities, _ = await resolver.resolve(extractions, episode_uuids)

        assert len(entities) == 2
        entity_types = {e.entity_type for e in entities}
        assert "technology" in entity_types or "Technology" in {e.entity_type for e in entities}

    @pytest.mark.asyncio
    async def test_canonical_name_picks_longest_variant(self, resolver: EntityResolver) -> None:
        """The longest raw name variant is chosen as canonical."""
        extractions = {
            "chunk-1": _make_extraction([
                ("Platform Team", "Team", "Short name."),
            ]),
            "chunk-2": _make_extraction([
                ("platform team", "Team", "Full name, much longer summary for more context."),
            ]),
            "chunk-3": _make_extraction([
                ("PLATFORM TEAM", "Team", "Mid."),
            ]),
        }
        episode_uuids = {
            "chunk-1": "ep-1",
            "chunk-2": "ep-2",
            "chunk-3": "ep-3",
        }

        entities, _ = await resolver.resolve(extractions, episode_uuids)

        # All normalize to "platform team" / "team" -> one entity
        assert len(entities) == 1
        # "PLATFORM TEAM" (len=13) and "Platform Team" (len=13) are tied;
        # "platform team" (len=13) also the same length.
        # Any of these is acceptable as canonical -- just verify it's one of them.
        assert entities[0].canonical_name in {
            "Platform Team", "platform team", "PLATFORM TEAM"
        }

    @pytest.mark.asyncio
    async def test_raw_names_accumulated(self, resolver: EntityResolver) -> None:
        """All surface-form name variants are kept in raw_names."""
        extractions = {
            "chunk-1": _make_extraction([
                ("Platform Team", "Team", "S1."),
            ]),
            "chunk-2": _make_extraction([
                ("platform team", "Team", "S2."),
            ]),
            "chunk-3": _make_extraction([
                ("PLATFORM TEAM", "Team", "S3."),
            ]),
        }
        episode_uuids = {
            "chunk-1": "ep-1",
            "chunk-2": "ep-2",
            "chunk-3": "ep-3",
        }

        entities, _ = await resolver.resolve(extractions, episode_uuids)
        assert len(entities) == 1
        assert "Platform Team" in entities[0].raw_names
        assert "platform team" in entities[0].raw_names
        assert "PLATFORM TEAM" in entities[0].raw_names


# ---------------------------------------------------------------------------
# Relationship resolution
# ---------------------------------------------------------------------------


class TestRelationshipResolution:
    """Tests for relationship mapping, deduplication, and filtering."""

    @pytest.mark.asyncio
    async def test_relationship_mapped_to_resolved_uuids(self, resolver: EntityResolver) -> None:
        """Relationships reference resolved entity UUIDs, not raw names."""
        extractions = {
            "chunk-1": _make_extraction(
                entities=[
                    ("Alice", "Person", "An engineer."),
                    ("Platform Team", "Team", "A team."),
                ],
                relationships=[
                    ("Alice", "Platform Team", "member_of", "Alice is on Platform Team."),
                ],
            ),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        entities, relationships = await resolver.resolve(extractions, episode_uuids)

        assert len(relationships) == 1
        rel = relationships[0]

        entity_by_uuid = {e.uuid: e for e in entities}
        assert rel.source_entity_uuid in entity_by_uuid
        assert rel.target_entity_uuid in entity_by_uuid
        assert entity_by_uuid[rel.source_entity_uuid].canonical_name == "Alice"
        assert entity_by_uuid[rel.target_entity_uuid].canonical_name == "Platform Team"

    @pytest.mark.asyncio
    async def test_relationship_deduplication_merges_episodes(
        self, resolver: EntityResolver
    ) -> None:
        """Same (source, target, name) across chunks -> one relationship with merged episodes."""
        extractions = {
            "chunk-1": _make_extraction(
                entities=[
                    ("Alice", "Person", "An engineer."),
                    ("Platform Team", "Team", "A team."),
                ],
                relationships=[
                    ("Alice", "Platform Team", "member_of", "Alice is on PT."),
                ],
            ),
            "chunk-2": _make_extraction(
                entities=[
                    ("Alice", "Person", "Alice again."),
                    ("Platform Team", "Team", "Same team."),
                ],
                relationships=[
                    ("Alice", "Platform Team", "member_of", "Alice belongs to Platform Team since 2024."),
                ],
            ),
        }
        episode_uuids = {"chunk-1": "ep-1", "chunk-2": "ep-2"}

        _, relationships = await resolver.resolve(extractions, episode_uuids)

        assert len(relationships) == 1
        assert sorted(relationships[0].episode_uuids) == ["ep-1", "ep-2"]

    @pytest.mark.asyncio
    async def test_self_referential_edge_removed(self, resolver: EntityResolver) -> None:
        """Edges where source and target resolve to the same entity are dropped."""
        extractions = {
            "chunk-1": _make_extraction(
                entities=[
                    ("Platform Team", "Team", "A team."),
                    ("platform team", "Team", "Same team, different case."),
                ],
                relationships=[
                    ("Platform Team", "platform team", "same_as", "They are the same."),
                ],
            ),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        _, relationships = await resolver.resolve(extractions, episode_uuids)

        # The two entity names resolve to the same entity, so the edge is self-referential
        assert len(relationships) == 0

    @pytest.mark.asyncio
    async def test_unresolvable_entities_in_relationship_skipped(
        self, resolver: EntityResolver
    ) -> None:
        """Relationships referencing entities not in the extraction are skipped."""
        extractions = {
            "chunk-1": _make_extraction(
                entities=[
                    ("Alice", "Person", "An engineer."),
                ],
                relationships=[
                    # "Bob" is not in the entities list
                    ("Alice", "Bob", "works_with", "Alice works with Bob."),
                ],
            ),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        _, relationships = await resolver.resolve(extractions, episode_uuids)

        assert len(relationships) == 0

    @pytest.mark.asyncio
    async def test_relationship_fact_picks_longest(self, resolver: EntityResolver) -> None:
        """When deduplicating relationships, the longest fact is kept."""
        extractions = {
            "chunk-1": _make_extraction(
                entities=[
                    ("Alice", "Person", "S1."),
                    ("Bob", "Person", "S2."),
                ],
                relationships=[
                    ("Alice", "Bob", "manages", "Short fact."),
                ],
            ),
            "chunk-2": _make_extraction(
                entities=[
                    ("Alice", "Person", "S3."),
                    ("Bob", "Person", "S4."),
                ],
                relationships=[
                    ("Alice", "Bob", "manages", "This is a much longer and more detailed factual statement about the management relationship."),
                ],
            ),
        }
        episode_uuids = {"chunk-1": "ep-1", "chunk-2": "ep-2"}

        _, relationships = await resolver.resolve(extractions, episode_uuids)

        assert len(relationships) == 1
        assert "much longer" in relationships[0].fact


# ---------------------------------------------------------------------------
# Episode mentions
# ---------------------------------------------------------------------------


class TestEpisodeMentions:
    """Tests for mentioned_in_episodes population."""

    @pytest.mark.asyncio
    async def test_mentioned_in_episodes_populated(self, resolver: EntityResolver) -> None:
        """Each entity's mentioned_in_episodes lists the episodes it appeared in."""
        extractions = {
            "chunk-1": _make_extraction([
                ("Alice", "Person", "An engineer."),
                ("Bob", "Person", "Another engineer."),
            ]),
            "chunk-2": _make_extraction([
                ("Alice", "Person", "Alice again."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1", "chunk-2": "ep-2"}

        entities, _ = await resolver.resolve(extractions, episode_uuids)

        entities_by_name = {
            e.canonical_name.lower(): e for e in entities
        }

        alice = entities_by_name["alice"]
        bob = entities_by_name["bob"]

        assert sorted(alice.mentioned_in_episodes) == ["ep-1", "ep-2"]
        assert bob.mentioned_in_episodes == ["ep-1"]

    @pytest.mark.asyncio
    async def test_missing_episode_uuid_skipped(self, resolver: EntityResolver) -> None:
        """Chunks without episode UUIDs do not contribute to mentions."""
        extractions = {
            "chunk-1": _make_extraction([
                ("Alice", "Person", "An engineer."),
            ]),
            "chunk-2": _make_extraction([
                ("Alice", "Person", "Alice again."),
            ]),
        }
        # chunk-2 has no episode UUID
        episode_uuids = {"chunk-1": "ep-1"}

        entities, _ = await resolver.resolve(extractions, episode_uuids)

        assert len(entities) == 1
        assert entities[0].mentioned_in_episodes == ["ep-1"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for the resolver."""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, resolver: EntityResolver) -> None:
        """No extractions -> no entities, no relationships."""
        entities, relationships = await resolver.resolve({}, {})
        assert entities == []
        assert relationships == []

    @pytest.mark.asyncio
    async def test_extraction_with_no_entities_or_relationships(
        self, resolver: EntityResolver
    ) -> None:
        """Chunks with empty entity/relationship lists produce nothing."""
        extractions = {
            "chunk-1": _make_extraction(entities=[], relationships=[]),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        entities, relationships = await resolver.resolve(extractions, episode_uuids)
        assert entities == []
        assert relationships == []

    @pytest.mark.asyncio
    async def test_entity_uuid_is_unique(self, resolver: EntityResolver) -> None:
        """Each resolved entity gets a unique UUID."""
        extractions = {
            "chunk-1": _make_extraction([
                ("Alice", "Person", "S1."),
                ("Bob", "Person", "S2."),
                ("Platform Team", "Team", "S3."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        entities, _ = await resolver.resolve(extractions, episode_uuids)

        uuids = [e.uuid for e in entities]
        assert len(uuids) == len(set(uuids))

    @pytest.mark.asyncio
    async def test_relationship_uuid_is_unique(self, resolver: EntityResolver) -> None:
        """Each resolved relationship gets a unique UUID."""
        extractions = {
            "chunk-1": _make_extraction(
                entities=[
                    ("Alice", "Person", "S1."),
                    ("Bob", "Person", "S2."),
                    ("Charlie", "Person", "S3."),
                ],
                relationships=[
                    ("Alice", "Bob", "manages", "F1."),
                    ("Bob", "Charlie", "mentors", "F2."),
                    ("Alice", "Charlie", "supervises", "F3."),
                ],
            ),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        _, relationships = await resolver.resolve(extractions, episode_uuids)

        uuids = [r.uuid for r in relationships]
        assert len(uuids) == len(set(uuids))

    def test_custom_similarity_threshold(self) -> None:
        """EntityResolver accepts a custom similarity threshold."""
        resolver = EntityResolver(similarity_threshold=0.95)
        assert resolver.similarity_threshold == 0.95

    def test_default_similarity_threshold_from_settings(self) -> None:
        """Without explicit threshold, settings value is used."""
        with patch("knowledge_base.batch.resolver.settings") as mock_settings:
            mock_settings.BATCH_ENTITY_SIMILARITY_THRESHOLD = 0.75
            resolver = EntityResolver()
            assert resolver.similarity_threshold == 0.75
