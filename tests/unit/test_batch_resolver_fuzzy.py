"""Tests for fuzzy entity merge in the batch resolver."""

from unittest.mock import AsyncMock, patch

import pytest

from knowledge_base.batch.models import (
    ChunkExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
)
from knowledge_base.batch.resolver import (
    EntityResolver,
    _UnionFind,
    _cosine_similarity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_extraction(
    entities: list[tuple[str, str, str]],
    relationships: list[tuple[str, str, str, str]] | None = None,
    summary: str = "Test summary.",
) -> ChunkExtractionResult:
    """Build a ChunkExtractionResult from simple tuples."""
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


def _similar_vector(base: list[float], noise: float = 0.01) -> list[float]:
    """Create a vector similar to base by adding small noise."""
    return [x + noise for x in base]


def _distant_vector(base: list[float]) -> list[float]:
    """Create a vector very different from base."""
    return [-x for x in base]


@pytest.fixture
def fuzzy_resolver():
    """Create an EntityResolver with fuzzy merge enabled."""
    with patch("knowledge_base.batch.resolver.settings") as mock_settings:
        mock_settings.BATCH_ENTITY_SIMILARITY_THRESHOLD = 0.85
        mock_settings.BATCH_ENTITY_FUZZY_MERGE_ENABLED = True
        mock_settings.BATCH_FUZZY_MERGE_BATCH_SIZE = 500
        yield EntityResolver()


@pytest.fixture
def disabled_resolver():
    """Create an EntityResolver with fuzzy merge disabled."""
    with patch("knowledge_base.batch.resolver.settings") as mock_settings:
        mock_settings.BATCH_ENTITY_SIMILARITY_THRESHOLD = 0.85
        mock_settings.BATCH_ENTITY_FUZZY_MERGE_ENABLED = False
        yield EntityResolver()


# ---------------------------------------------------------------------------
# _cosine_similarity tests
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    """Tests for the _cosine_similarity helper."""

    def test_identical_vectors(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 2.0, 3.0]
        b = [-1.0, -2.0, -3.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self) -> None:
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_both_zero_returns_zero(self) -> None:
        a = [0.0, 0.0]
        b = [0.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0


# ---------------------------------------------------------------------------
# _UnionFind tests
# ---------------------------------------------------------------------------


class TestUnionFind:
    """Tests for the union-find data structure."""

    def test_initial_state(self) -> None:
        uf = _UnionFind(3)
        assert uf.find(0) == 0
        assert uf.find(1) == 1
        assert uf.find(2) == 2

    def test_union_merges(self) -> None:
        uf = _UnionFind(3)
        uf.union(0, 1)
        assert uf.find(0) == uf.find(1)
        assert uf.find(2) != uf.find(0)

    def test_transitive_union(self) -> None:
        uf = _UnionFind(4)
        uf.union(0, 1)
        uf.union(2, 3)
        uf.union(1, 2)
        # All four should be in the same set
        root = uf.find(0)
        assert uf.find(1) == root
        assert uf.find(2) == root
        assert uf.find(3) == root


# ---------------------------------------------------------------------------
# Fuzzy merge integration tests
# ---------------------------------------------------------------------------


class TestFuzzyMerge:
    """Tests for fuzzy entity merge via embedding similarity."""

    @pytest.mark.asyncio
    async def test_merges_similar_entities(self, fuzzy_resolver: EntityResolver) -> None:
        """Entities of the same type with similar embeddings are merged."""
        base_vec = [1.0, 0.5, 0.3, 0.8]
        similar_vec = _similar_vector(base_vec, noise=0.005)

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(
            return_value=[base_vec, similar_vec]
        )

        extractions = {
            "chunk-1": _make_extraction([
                ("Platform Team", "Team", "Owns infrastructure."),
            ]),
            "chunk-2": _make_extraction([
                ("Platform-Team", "Team", "Manages CI/CD."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1", "chunk-2": "ep-2"}

        with patch(
            "knowledge_base.vectorstore.embeddings.get_embeddings",
            return_value=mock_embedder,
        ):
            entities, _ = await fuzzy_resolver.resolve(extractions, episode_uuids)

        # The two should be merged into one
        assert len(entities) == 1
        # Both raw names should be present
        raw = entities[0].raw_names
        assert "Platform Team" in raw
        assert "Platform-Team" in raw

    @pytest.mark.asyncio
    async def test_no_merge_below_threshold(self, fuzzy_resolver: EntityResolver) -> None:
        """Entities with low similarity are NOT merged."""
        base_vec = [1.0, 0.0, 0.0, 0.0]
        distant_vec = _distant_vector(base_vec)

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(
            return_value=[base_vec, distant_vec]
        )

        extractions = {
            "chunk-1": _make_extraction([
                ("Platform Team", "Team", "Owns infrastructure."),
            ]),
            "chunk-2": _make_extraction([
                ("Security Team", "Team", "Handles security."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1", "chunk-2": "ep-2"}

        with patch(
            "knowledge_base.vectorstore.embeddings.get_embeddings",
            return_value=mock_embedder,
        ):
            entities, _ = await fuzzy_resolver.resolve(extractions, episode_uuids)

        # Should remain separate
        assert len(entities) == 2

    @pytest.mark.asyncio
    async def test_no_merge_across_entity_types(self, fuzzy_resolver: EntityResolver) -> None:
        """Entities of different types are never merged, even if names are identical."""
        vec = [1.0, 0.5, 0.3, 0.8]

        # Each type bucket gets its own embed call (single item each)
        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(side_effect=[[vec], [vec]])

        extractions = {
            "chunk-1": _make_extraction([
                ("Mercury", "Technology", "A messaging system."),
                ("Mercury", "Person", "A team member."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        with patch(
            "knowledge_base.vectorstore.embeddings.get_embeddings",
            return_value=mock_embedder,
        ):
            entities, _ = await fuzzy_resolver.resolve(extractions, episode_uuids)

        assert len(entities) == 2
        types = {e.entity_type for e in entities}
        assert len(types) == 2

    @pytest.mark.asyncio
    async def test_transitive_merge_single_linkage(self, fuzzy_resolver: EntityResolver) -> None:
        """A-B similar, B-C similar -> all three merged (single-linkage)."""
        # A and C are not directly similar, but B bridges them
        vec_a = [1.0, 0.0, 0.0, 0.0]
        vec_b = [0.9, 0.4, 0.0, 0.0]  # similar to A
        vec_c = [0.5, 0.85, 0.0, 0.0]  # similar to B but not to A

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[vec_a, vec_b, vec_c])

        extractions = {
            "chunk-1": _make_extraction([("TeamA", "Team", "S1.")]),
            "chunk-2": _make_extraction([("TeamB", "Team", "S2.")]),
            "chunk-3": _make_extraction([("TeamC", "Team", "S3.")]),
        }
        episode_uuids = {"chunk-1": "ep-1", "chunk-2": "ep-2", "chunk-3": "ep-3"}

        # Use a low threshold so A-B and B-C pass but verify transitivity
        with patch("knowledge_base.batch.resolver.settings") as mock_settings:
            mock_settings.BATCH_ENTITY_SIMILARITY_THRESHOLD = 0.80
            mock_settings.BATCH_ENTITY_FUZZY_MERGE_ENABLED = True
            mock_settings.BATCH_FUZZY_MERGE_BATCH_SIZE = 500
            resolver = EntityResolver()

            with patch(
                "knowledge_base.vectorstore.embeddings.get_embeddings",
                return_value=mock_embedder,
            ):
                entities, _ = await resolver.resolve(extractions, episode_uuids)

        # Check A-B similarity and B-C similarity pass threshold
        sim_ab = _cosine_similarity(vec_a, vec_b)
        sim_bc = _cosine_similarity(vec_b, vec_c)
        assert sim_ab >= 0.80, f"A-B sim {sim_ab} should be >= 0.80"
        assert sim_bc >= 0.80, f"B-C sim {sim_bc} should be >= 0.80"

        # All three should be merged into one via single-linkage
        assert len(entities) == 1
        assert len(entities[0].raw_names) == 3

    @pytest.mark.asyncio
    async def test_preserves_summaries_and_source_chunks(
        self, fuzzy_resolver: EntityResolver
    ) -> None:
        """Merged entities accumulate summaries and source_chunk_ids."""
        base_vec = [1.0, 0.5, 0.3, 0.8]
        similar_vec = _similar_vector(base_vec, noise=0.005)

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(
            return_value=[base_vec, similar_vec]
        )

        extractions = {
            "chunk-1": _make_extraction([
                ("Platform Team", "Team", "Summary from chunk 1."),
            ]),
            "chunk-2": _make_extraction([
                ("Platform-Team", "Team", "Summary from chunk 2, more detailed."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1", "chunk-2": "ep-2"}

        with patch(
            "knowledge_base.vectorstore.embeddings.get_embeddings",
            return_value=mock_embedder,
        ):
            entities, _ = await fuzzy_resolver.resolve(extractions, episode_uuids)

        assert len(entities) == 1
        # The longest summary should be picked as canonical
        assert "more detailed" in entities[0].summary
        # Both episodes should be mentioned
        assert sorted(entities[0].mentioned_in_episodes) == ["ep-1", "ep-2"]

    @pytest.mark.asyncio
    async def test_feature_flag_disabled_skips_merge(
        self, disabled_resolver: EntityResolver
    ) -> None:
        """When BATCH_ENTITY_FUZZY_MERGE_ENABLED=False, no embedding calls are made."""
        extractions = {
            "chunk-1": _make_extraction([
                ("Platform Team", "Team", "S1."),
            ]),
            "chunk-2": _make_extraction([
                ("Platform-Team", "Team", "S2."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1", "chunk-2": "ep-2"}

        # No mock needed -- embeddings should never be called
        entities, _ = await disabled_resolver.resolve(extractions, episode_uuids)

        # Without fuzzy merge, these are separate (different normalized names)
        assert len(entities) == 2

    @pytest.mark.asyncio
    async def test_empty_input(self, fuzzy_resolver: EntityResolver) -> None:
        """Empty extractions produce no entities even with fuzzy merge enabled."""
        entities, relationships = await fuzzy_resolver.resolve({}, {})
        assert entities == []
        assert relationships == []

    @pytest.mark.asyncio
    async def test_single_group_no_merge_needed(
        self, fuzzy_resolver: EntityResolver
    ) -> None:
        """A single entity group within a type needs no pairwise comparison."""
        mock_embedder = AsyncMock()
        # Should not be called since there's only one group per type
        mock_embedder.embed = AsyncMock(return_value=[[1.0, 0.5]])

        extractions = {
            "chunk-1": _make_extraction([
                ("Alice", "Person", "An engineer."),
            ]),
        }
        episode_uuids = {"chunk-1": "ep-1"}

        with patch(
            "knowledge_base.vectorstore.embeddings.get_embeddings",
            return_value=mock_embedder,
        ):
            entities, _ = await fuzzy_resolver.resolve(extractions, episode_uuids)

        assert len(entities) == 1
        assert entities[0].canonical_name == "Alice"
        # embed should NOT have been called (single group in type bucket)
        mock_embedder.embed.assert_not_called()
