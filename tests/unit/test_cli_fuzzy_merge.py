"""Tests for fuzzy-merge HNSW candidate discovery and prune-entities logic."""

import re
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.batch.resolver import _UnionFind
from knowledge_base.cli import _JUNK_ENTITY_PATTERNS


# ---------------------------------------------------------------------------
# Junk pattern tests
# ---------------------------------------------------------------------------


class TestJunkEntityPatterns:
    """Verify the regex patterns match expected junk entity names."""

    @pytest.mark.parametrize(
        "name",
        [
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "6fcd3f38-3989-411f-a32f-dad2716e15dd",
            "083f01eb-11a3-4a68-9104-1caa833c821b",
        ],
    )
    def test_uuid_pattern_matches(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[0][0]
        assert re.match(pattern, name), f"UUID pattern should match: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "Platform Team",
            "Keboola",
            "a1b2c3d4",  # too short for UUID format
        ],
    )
    def test_uuid_pattern_rejects(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[0][0]
        assert not re.match(pattern, name), f"UUID pattern should NOT match: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "a" * 32,
            "0123456789abcdef0123456789abcdef",
            "a" * 64,
        ],
    )
    def test_sha_hash_pattern_matches(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[1][0]
        assert re.match(pattern, name), f"SHA pattern should match: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "abc",  # too short
            "ABCDEF" * 6,  # uppercase hex
            "not-a-hash-at-all",
        ],
    )
    def test_sha_hash_pattern_rejects(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[1][0]
        assert not re.match(pattern, name), f"SHA pattern should NOT match: {name}"

    @pytest.mark.parametrize("name", ["1234", "56789", "0000000"])
    def test_numeric_id_pattern_matches(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[2][0]
        assert re.match(pattern, name), f"Numeric pattern should match: {name}"

    @pytest.mark.parametrize("name", ["123", "42", "v1.0"])
    def test_numeric_id_pattern_rejects(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[2][0]
        assert not re.match(pattern, name), f"Numeric pattern should NOT match: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "PLG-56a830f219",
            "PST-1518a830f219",
            "CFT-3042a830f219",
            "CT-1171a830f219",
            "QID-228650566",
        ],
    )
    def test_internal_id_pattern_matches(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[3][0]
        assert re.match(pattern, name), f"Internal ID pattern should match: {name}"

    @pytest.mark.parametrize("name", ["Platform", "CTO", "QA Team"])
    def test_internal_id_pattern_rejects(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[3][0]
        assert not re.match(pattern, name), f"Internal ID pattern should NOT match: {name}"

    @pytest.mark.parametrize(
        "name",
        [
            "https://example.com",
            "http://localhost:8080/api",
        ],
    )
    def test_url_pattern_matches(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[4][0]
        assert re.match(pattern, name), f"URL pattern should match: {name}"

    @pytest.mark.parametrize("name", ["Keboola", "HTTP Client"])
    def test_url_pattern_rejects(self, name: str) -> None:
        pattern = _JUNK_ENTITY_PATTERNS[4][0]
        assert not re.match(pattern, name), f"URL pattern should NOT match: {name}"


# ---------------------------------------------------------------------------
# Union-Find with HNSW-sourced pairs
# ---------------------------------------------------------------------------


class TestUnionFindWithHnswPairs:
    """Verify Union-Find clustering works with HNSW candidate pairs."""

    def test_simple_pair(self) -> None:
        uf = _UnionFind(3)
        uf.union(0, 1)
        assert uf.find(0) == uf.find(1)
        assert uf.find(0) != uf.find(2)

    def test_transitive_merge(self) -> None:
        """A~B and B~C should put A, B, C in same cluster."""
        uf = _UnionFind(4)
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.find(0) == uf.find(2)
        assert uf.find(0) != uf.find(3)

    def test_cluster_extraction(self) -> None:
        """Extract clusters from Union-Find matches HNSW candidate format."""
        # Simulate HNSW candidates: (A,B), (B,C), (D,E)
        uuids = ["A", "B", "C", "D", "E"]
        uuid_idx = {u: i for i, u in enumerate(uuids)}

        uf = _UnionFind(len(uuids))
        pairs = [("A", "B"), ("B", "C"), ("D", "E")]
        for a, b in pairs:
            uf.union(uuid_idx[a], uuid_idx[b])

        clusters: dict[int, list[int]] = defaultdict(list)
        for i in range(len(uuids)):
            clusters[uf.find(i)].append(i)

        multi_clusters = [m for m in clusters.values() if len(m) > 1]
        assert len(multi_clusters) == 2
        sizes = sorted(len(c) for c in multi_clusters)
        assert sizes == [2, 3]  # {A,B,C} and {D,E}

    def test_no_pairs_no_clusters(self) -> None:
        uf = _UnionFind(5)
        clusters: dict[int, list[int]] = defaultdict(list)
        for i in range(5):
            clusters[uf.find(i)].append(i)
        multi = [m for m in clusters.values() if len(m) > 1]
        assert len(multi) == 0


# ---------------------------------------------------------------------------
# HNSW query construction
# ---------------------------------------------------------------------------


class TestHnswQueryConstruction:
    """Verify the HNSW candidate discovery query structure."""

    def test_query_contains_hnsw_call(self) -> None:
        """The HNSW query must use db.index.vector.queryNodes."""
        # This is a structural test: verify the query string in the function
        from knowledge_base.cli import _fuzzy_merge_discover_candidates_hnsw
        import inspect

        source = inspect.getsource(_fuzzy_merge_discover_candidates_hnsw)
        assert "db.index.vector.queryNodes" in source
        assert "entity_name_embedding" in source

    def test_query_filters_same_type(self) -> None:
        """The query must filter candidates to same entity_type."""
        from knowledge_base.cli import _fuzzy_merge_discover_candidates_hnsw
        import inspect

        source = inspect.getsource(_fuzzy_merge_discover_candidates_hnsw)
        assert "candidate.entity_type = $etype" in source

    def test_query_prevents_symmetric_pairs(self) -> None:
        """e.uuid < candidate.uuid prevents (A,B) and (B,A)."""
        from knowledge_base.cli import _fuzzy_merge_discover_candidates_hnsw
        import inspect

        source = inspect.getsource(_fuzzy_merge_discover_candidates_hnsw)
        assert "e.uuid < candidate.uuid" in source

    def test_query_uses_pagination(self) -> None:
        """SKIP/LIMIT pagination for memory-bounded processing."""
        from knowledge_base.cli import _fuzzy_merge_discover_candidates_hnsw
        import inspect

        source = inspect.getsource(_fuzzy_merge_discover_candidates_hnsw)
        assert "SKIP $offset" in source
        assert "LIMIT $batch_size" in source


# ---------------------------------------------------------------------------
# Merge Cypher safety
# ---------------------------------------------------------------------------


class TestMergeCypherSafety:
    """Verify the merge Cypher uses MATCH (not MERGE) for canonical entity."""

    def test_merge_uses_match_for_canonical(self) -> None:
        """Canonical entity must be found via MATCH, not created via MERGE."""
        from knowledge_base.cli import _fuzzy_merge_apply
        import inspect

        source = inspect.getsource(_fuzzy_merge_apply)
        # Must MATCH both canonical and duplicate
        assert "MATCH (c:Entity {uuid: $c}), (d:Entity {uuid: $d})" in source
        # Must NOT have bare MERGE (:Entity {uuid: $c}) which creates new nodes
        assert "MERGE (:Entity {uuid: $c})" not in source

    def test_merge_uses_single_query(self) -> None:
        """All edge redirects + delete in a single Cypher query."""
        from knowledge_base.cli import _fuzzy_merge_apply
        import inspect

        source = inspect.getsource(_fuzzy_merge_apply)
        # Single query with FOREACH for all edge types
        assert "FOREACH" in source
        assert "DETACH DELETE d" in source

    def test_cluster_size_cap_in_apply(self) -> None:
        """Clusters exceeding max size are skipped."""
        from knowledge_base.cli import _fuzzy_merge_apply
        import inspect

        source = inspect.getsource(_fuzzy_merge_apply)
        assert "max_cluster" in source
        assert "FUZZY_MERGE_MAX_CLUSTER_SIZE" in source


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestFuzzyMergeConfig:
    """Verify config defaults for HNSW fuzzy merge and pruning."""

    def test_hnsw_k_default(self) -> None:
        from knowledge_base.config import Settings
        s = Settings(
            NEO4J_URI="bolt://test:7687",
            NEO4J_PASSWORD="test-only-not-real",  # noqa: S106
        )
        assert s.FUZZY_MERGE_HNSW_K == 10

    def test_query_batch_size_default(self) -> None:
        from knowledge_base.config import Settings
        s = Settings(
            NEO4J_URI="bolt://test:7687",
            NEO4J_PASSWORD="test-only-not-real",  # noqa: S106
        )
        assert s.FUZZY_MERGE_QUERY_BATCH_SIZE == 200

    def test_max_type_size_default_unlimited(self) -> None:
        from knowledge_base.config import Settings
        s = Settings(
            NEO4J_URI="bolt://test:7687",
            NEO4J_PASSWORD="test-only-not-real",  # noqa: S106
        )
        assert s.FUZZY_MERGE_MAX_TYPE_SIZE == 0

    def test_max_cluster_size_default(self) -> None:
        from knowledge_base.config import Settings
        s = Settings(
            NEO4J_URI="bolt://test:7687",
            NEO4J_PASSWORD="test-only-not-real",  # noqa: S106
        )
        assert s.FUZZY_MERGE_MAX_CLUSTER_SIZE == 50

    def test_prune_min_name_length_default(self) -> None:
        from knowledge_base.config import Settings
        s = Settings(
            NEO4J_URI="bolt://test:7687",
            NEO4J_PASSWORD="test-only-not-real",  # noqa: S106
        )
        assert s.PRUNE_ENTITY_MIN_NAME_LENGTH == 3
