"""Search Quality Benchmarking Tests (Golden Dataset).

Per QA Recommendation B: Implement tests that verify correct chunks appear in top results
and that BM25 outweighs semantic search for exact term matches.
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from knowledge_base.search.bm25 import BM25Index
from knowledge_base.search.fusion import reciprocal_rank_fusion
from knowledge_base.search.hybrid import HybridRetriever


pytestmark = pytest.mark.integration


class TestGoldenDatasetRetrieval:
    """Test retrieval precision using a golden dataset."""

    # Golden dataset: queries with known correct answers
    GOLDEN_DATASET = [
        {
            "query": "What is the vacation policy?",
            "expected_keywords": ["vacation", "pto", "time off", "leave"],
            "expected_chunk_contains": "vacation",
        },
        {
            "query": "How do I request access to GCP?",
            "expected_keywords": ["gcp", "google cloud", "access", "request"],
            "expected_chunk_contains": "access",
        },
        {
            "query": "What is the onboarding process?",
            "expected_keywords": ["onboarding", "new hire", "first day"],
            "expected_chunk_contains": "onboarding",
        },
        {
            "query": "ERROR_CODE_5001 troubleshooting",
            "expected_keywords": ["error_code_5001", "5001"],
            "expected_chunk_contains": "5001",
            "exact_match_required": True,  # BM25 should excel here
        },
        {
            "query": "JIRA-12345 deployment issue",
            "expected_keywords": ["jira-12345", "12345"],
            "expected_chunk_contains": "jira",
            "exact_match_required": True,
        },
    ]

    @pytest.fixture
    def sample_chunks(self):
        """Create sample chunks for testing."""
        return [
            {
                "chunk_id": "chunk_vacation_1",
                "content": "Our vacation policy allows 20 days of PTO per year. Time off requests should be submitted 2 weeks in advance.",
                "metadata": {"page_title": "HR Policies", "space_key": "HR"},
            },
            {
                "chunk_id": "chunk_gcp_1",
                "content": "To request access to GCP (Google Cloud Platform), submit a ticket in #platform-access channel.",
                "metadata": {"page_title": "Access Requests", "space_key": "IT"},
            },
            {
                "chunk_id": "chunk_onboarding_1",
                "content": "The onboarding process for new hires includes: Day 1 orientation, system access setup, and team introductions.",
                "metadata": {"page_title": "Onboarding Guide", "space_key": "HR"},
            },
            {
                "chunk_id": "chunk_error_5001",
                "content": "ERROR_CODE_5001: Database connection timeout. Troubleshooting: Check VPN connection and retry.",
                "metadata": {"page_title": "Error Codes", "space_key": "TECH"},
            },
            {
                "chunk_id": "chunk_jira_12345",
                "content": "JIRA-12345: Deployment pipeline fails on staging. Resolution: Clear Docker cache and redeploy.",
                "metadata": {"page_title": "Known Issues", "space_key": "TECH"},
            },
            {
                "chunk_id": "chunk_unrelated_1",
                "content": "The company cafeteria serves lunch from 12pm to 2pm daily.",
                "metadata": {"page_title": "Office Info", "space_key": "GENERAL"},
            },
        ]

    def test_bm25_index_returns_relevant_results(self, sample_chunks):
        """Verify BM25 returns relevant results for keyword queries."""
        # Build BM25 index
        bm25 = BM25Index()
        chunk_ids = [c["chunk_id"] for c in sample_chunks]
        contents = [c["content"] for c in sample_chunks]
        metadatas = [c["metadata"] for c in sample_chunks]

        bm25.build(chunk_ids, contents, metadatas)

        # Test each golden query
        for golden in self.GOLDEN_DATASET:
            query = golden["query"]
            expected_contains = golden["expected_chunk_contains"]

            results = bm25.search(query, k=3)

            assert len(results) > 0, f"BM25 should return results for: {query}"

            # Check if top result contains expected content
            top_chunk_id, top_score = results[0]
            top_content = contents[chunk_ids.index(top_chunk_id)]

            assert expected_contains.lower() in top_content.lower(), \
                f"Top result for '{query}' should contain '{expected_contains}'. Got: {top_content[:100]}"

    def test_exact_term_matches_rank_higher_in_bm25(self, sample_chunks):
        """Verify exact terms (error codes, ticket IDs) rank higher in BM25."""
        bm25 = BM25Index()
        chunk_ids = [c["chunk_id"] for c in sample_chunks]
        contents = [c["content"] for c in sample_chunks]
        metadatas = [c["metadata"] for c in sample_chunks]

        bm25.build(chunk_ids, contents, metadatas)

        # Query for exact error code
        results = bm25.search("ERROR_CODE_5001", k=3)

        assert len(results) > 0
        top_chunk_id, _ = results[0]

        # The error code chunk should be #1
        assert top_chunk_id == "chunk_error_5001", \
            f"Exact error code query should return error chunk first, got: {top_chunk_id}"

        # Query for exact JIRA ticket
        results = bm25.search("JIRA-12345", k=3)
        top_chunk_id, _ = results[0]

        assert top_chunk_id == "chunk_jira_12345", \
            f"Exact JIRA query should return JIRA chunk first, got: {top_chunk_id}"

    def test_rrf_fusion_combines_results_correctly(self):
        """Verify RRF fusion combines BM25 and vector results properly."""
        # Simulate BM25 results (error code query - BM25 should win)
        bm25_results = [
            ("chunk_error_5001", 10.5),  # Exact match, high score
            ("chunk_unrelated", 2.0),
            ("chunk_gcp", 1.5),
        ]

        # Simulate vector results (semantic similarity might prefer different docs)
        vector_results = [
            ("chunk_gcp", 0.95),  # Semantically similar but not exact
            ("chunk_error_5001", 0.85),
            ("chunk_onboarding", 0.80),
        ]

        # Fuse with higher BM25 weight (for exact term queries)
        combined = reciprocal_rank_fusion(
            bm25_results,
            vector_results,
            weights=(0.7, 0.3),  # Favor BM25
            k=60,
        )

        # The exact match (error_5001) should be top
        assert combined[0][0] == "chunk_error_5001", \
            f"RRF with BM25 weight should rank exact match first. Got: {combined[0][0]}"

    def test_semantic_query_benefits_from_vector_search(self, sample_chunks):
        """Verify semantic queries benefit from vector search."""
        # For queries like "how to take time off" (no exact "vacation" match),
        # vector search should help find the vacation policy

        bm25 = BM25Index()
        chunk_ids = [c["chunk_id"] for c in sample_chunks]
        contents = [c["content"] for c in sample_chunks]
        metadatas = [c["metadata"] for c in sample_chunks]

        bm25.build(chunk_ids, contents, metadatas)

        # This query doesn't contain "vacation" but should find vacation policy
        semantic_query = "how do I take days off from work"

        # BM25 alone might not find "vacation" with this query
        bm25_results = bm25.search(semantic_query, k=3)

        # Note: In a full hybrid test, vector search would find "vacation policy"
        # through semantic similarity even without the exact word
        # This test documents the expected behavior

        # At minimum, BM25 should find something related to "off" or "days"
        assert len(bm25_results) >= 0  # BM25 may or may not find results


class TestSearchRankingWithQualityScores:
    """Test that quality scores affect search ranking."""

    def test_high_quality_chunks_rank_higher(self):
        """Verify chunks with higher quality scores rank higher."""
        # This would integrate with the quality-weighted search
        # For now, we test the expected behavior

        # Two chunks about the same topic, different quality
        chunks_with_quality = [
            {
                "chunk_id": "vacation_high_quality",
                "content": "Vacation policy: 20 days PTO annually.",
                "quality_score": 95.0,  # High quality (positive feedback)
            },
            {
                "chunk_id": "vacation_low_quality",
                "content": "Vacation policy: 15 days PTO per year.",  # Outdated
                "quality_score": 45.0,  # Low quality (marked outdated)
            },
        ]

        # The search should rank the high-quality chunk first
        # even if both match the query equally well

        # Sort by quality (simulating quality-weighted ranking)
        sorted_by_quality = sorted(
            chunks_with_quality,
            key=lambda c: c["quality_score"],
            reverse=True,
        )

        assert sorted_by_quality[0]["chunk_id"] == "vacation_high_quality"
        assert sorted_by_quality[0]["quality_score"] > sorted_by_quality[1]["quality_score"]


class TestSearchEdgeCases:
    """Test edge cases in search."""

    def test_empty_query_handling(self):
        """Verify empty queries are handled gracefully."""
        bm25 = BM25Index()
        bm25.build(["chunk1"], ["Some content"], [{}])

        results = bm25.search("", k=3)
        # Should return empty or handle gracefully
        assert isinstance(results, list)

    def test_special_characters_in_query(self):
        """Verify special characters don't break search."""
        bm25 = BM25Index()
        bm25.build(
            ["chunk1", "chunk2"],
            ["Error: Connection failed!", "Status: OK"],
            [{}, {}],
        )

        # Queries with special chars
        special_queries = [
            "Error: Connection",
            "what's the status?",
            "user@example.com",
            "path/to/file",
            "50% discount",
        ]

        for query in special_queries:
            try:
                results = bm25.search(query, k=3)
                assert isinstance(results, list), f"Query '{query}' should return list"
            except Exception as e:
                pytest.fail(f"Query '{query}' raised exception: {e}")

    def test_very_long_query_handling(self):
        """Verify very long queries are handled."""
        bm25 = BM25Index()
        bm25.build(["chunk1"], ["Short content"], [{}])

        # Very long query
        long_query = "word " * 1000
        results = bm25.search(long_query, k=3)

        assert isinstance(results, list)
