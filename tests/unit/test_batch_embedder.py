"""Tests for batch embedding streaming methods (stream_embed_entities / stream_embed_edges)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.batch.embedder import BatchEmbedder
from knowledge_base.batch.models import ResolvedEntity, ResolvedRelationship


def _make_entity(
    uuid: str = "ent-1",
    canonical_name: str = "Platform Team",
    entity_type: str = "Team",
    summary: str = "A team.",
    name_embedding: list[float] | None = None,
) -> ResolvedEntity:
    return ResolvedEntity(
        uuid=uuid,
        canonical_name=canonical_name,
        entity_type=entity_type,
        summary=summary,
        name_embedding=name_embedding,
    )


def _make_relationship(
    uuid: str = "rel-1",
    source_entity_uuid: str = "ent-1",
    target_entity_uuid: str = "ent-2",
    relationship_name: str = "manages",
    fact: str = "Entity 1 manages Entity 2.",
    fact_embedding: list[float] | None = None,
) -> ResolvedRelationship:
    return ResolvedRelationship(
        uuid=uuid,
        source_entity_uuid=source_entity_uuid,
        target_entity_uuid=target_entity_uuid,
        relationship_name=relationship_name,
        fact=fact,
        fact_embedding=fact_embedding,
    )


def _fake_embed_fn(texts: list[str]) -> list[list[float]]:
    """Return a distinct fake 768-dim vector for each input text."""
    return [[float(i)] * 768 for i in range(len(texts))]


@pytest.fixture
def mock_settings():
    """Patch settings used by BatchEmbedder.__init__."""
    with patch("knowledge_base.batch.embedder.settings") as s:
        s.VERTEX_AI_BATCH_SIZE = 20
        s.BATCH_EMBEDDING_CONCURRENCY = 2
        yield s


@pytest.fixture
def mock_embedder_instance():
    """Create a mock BaseEmbeddings instance with an async embed method."""
    embedder = MagicMock()
    embedder.embed = AsyncMock(side_effect=_fake_embed_fn)
    return embedder


@pytest.fixture
def embedder(mock_settings, mock_embedder_instance):
    """Create a BatchEmbedder with mocked embedding provider."""
    with patch(
        "knowledge_base.batch.embedder.get_embeddings",
        return_value=mock_embedder_instance,
    ):
        return BatchEmbedder()


# ---------------------------------------------------------------------------
# stream_embed_entities tests
# ---------------------------------------------------------------------------


class TestStreamEmbedEntities:
    """Tests for stream_embed_entities."""

    @pytest.mark.asyncio
    async def test_calls_callback_with_uuid_embedding_pairs(
        self, embedder: BatchEmbedder, mock_embedder_instance: MagicMock
    ) -> None:
        """Callback receives (uuid, embedding) pairs for entities without embeddings."""
        entities = [
            _make_entity(uuid="ent-1", canonical_name="Alpha"),
            _make_entity(uuid="ent-2", canonical_name="Beta"),
            _make_entity(uuid="ent-3", canonical_name="Gamma"),
        ]

        on_batch = AsyncMock()
        count = await embedder.stream_embed_entities(entities, on_batch)

        assert count == 3
        assert on_batch.call_count >= 1

        # Collect all pairs across all on_batch calls
        all_pairs: list[tuple[str, list[float]]] = []
        for call in on_batch.call_args_list:
            all_pairs.extend(call[0][0])

        uuids_seen = [uid for uid, _ in all_pairs]
        assert set(uuids_seen) == {"ent-1", "ent-2", "ent-3"}

        # Each embedding should be a 768-dim list
        for _, emb in all_pairs:
            assert len(emb) == 768

    @pytest.mark.asyncio
    async def test_skips_already_embedded(
        self, embedder: BatchEmbedder, mock_embedder_instance: MagicMock
    ) -> None:
        """Entities with name_embedding already set are skipped."""
        entities = [
            _make_entity(uuid="ent-1", canonical_name="Alpha", name_embedding=[0.5] * 768),
            _make_entity(uuid="ent-2", canonical_name="Beta"),
        ]

        on_batch = AsyncMock()
        count = await embedder.stream_embed_entities(entities, on_batch)

        assert count == 1

        all_pairs: list[tuple[str, list[float]]] = []
        for call in on_batch.call_args_list:
            all_pairs.extend(call[0][0])

        uuids_seen = [uid for uid, _ in all_pairs]
        assert "ent-1" not in uuids_seen
        assert "ent-2" in uuids_seen

    @pytest.mark.asyncio
    async def test_skips_empty_names(
        self, embedder: BatchEmbedder, mock_embedder_instance: MagicMock
    ) -> None:
        """Entities with empty canonical_name are skipped."""
        entities = [
            _make_entity(uuid="ent-1", canonical_name=""),
            _make_entity(uuid="ent-2", canonical_name="   "),
            _make_entity(uuid="ent-3", canonical_name="Valid Name"),
        ]

        on_batch = AsyncMock()
        count = await embedder.stream_embed_entities(entities, on_batch)

        assert count == 1

        all_pairs: list[tuple[str, list[float]]] = []
        for call in on_batch.call_args_list:
            all_pairs.extend(call[0][0])

        uuids_seen = [uid for uid, _ in all_pairs]
        assert uuids_seen == ["ent-3"]


# ---------------------------------------------------------------------------
# stream_embed_edges tests
# ---------------------------------------------------------------------------


class TestStreamEmbedEdges:
    """Tests for stream_embed_edges."""

    @pytest.mark.asyncio
    async def test_calls_callback_with_uuid_embedding_pairs(
        self, embedder: BatchEmbedder, mock_embedder_instance: MagicMock
    ) -> None:
        """Callback receives (uuid, embedding) pairs for edges without embeddings."""
        relationships = [
            _make_relationship(uuid="rel-1", fact="Alpha manages Beta."),
            _make_relationship(uuid="rel-2", fact="Beta depends on Gamma."),
        ]

        on_batch = AsyncMock()
        count = await embedder.stream_embed_edges(relationships, on_batch)

        assert count == 2
        assert on_batch.call_count >= 1

        all_pairs: list[tuple[str, list[float]]] = []
        for call in on_batch.call_args_list:
            all_pairs.extend(call[0][0])

        uuids_seen = [uid for uid, _ in all_pairs]
        assert set(uuids_seen) == {"rel-1", "rel-2"}

        for _, emb in all_pairs:
            assert len(emb) == 768

    @pytest.mark.asyncio
    async def test_skips_already_embedded(
        self, embedder: BatchEmbedder, mock_embedder_instance: MagicMock
    ) -> None:
        """Edges with fact_embedding already set are skipped."""
        relationships = [
            _make_relationship(uuid="rel-1", fact="Alpha manages Beta.", fact_embedding=[0.5] * 768),
            _make_relationship(uuid="rel-2", fact="Beta depends on Gamma."),
        ]

        on_batch = AsyncMock()
        count = await embedder.stream_embed_edges(relationships, on_batch)

        assert count == 1

        all_pairs: list[tuple[str, list[float]]] = []
        for call in on_batch.call_args_list:
            all_pairs.extend(call[0][0])

        uuids_seen = [uid for uid, _ in all_pairs]
        assert "rel-1" not in uuids_seen
        assert "rel-2" in uuids_seen

    @pytest.mark.asyncio
    async def test_skips_empty_facts(
        self, embedder: BatchEmbedder, mock_embedder_instance: MagicMock
    ) -> None:
        """Edges with empty fact strings are skipped."""
        relationships = [
            _make_relationship(uuid="rel-1", fact=""),
            _make_relationship(uuid="rel-2", fact="   "),
            _make_relationship(uuid="rel-3", fact="Valid fact statement."),
        ]

        on_batch = AsyncMock()
        count = await embedder.stream_embed_edges(relationships, on_batch)

        assert count == 1

        all_pairs: list[tuple[str, list[float]]] = []
        for call in on_batch.call_args_list:
            all_pairs.extend(call[0][0])

        uuids_seen = [uid for uid, _ in all_pairs]
        assert uuids_seen == ["rel-3"]
