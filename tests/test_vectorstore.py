"""Tests for the vectorstore module.

Note: ChromaDB and VectorRetriever have been replaced with Graphiti.
See tests/test_graphiti_*.py for graph-based retriever tests.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from knowledge_base.vectorstore.embeddings import (
    BaseEmbeddings,
    SentenceTransformerEmbeddings,
    get_embeddings,
    get_available_embedding_providers,
)
from knowledge_base.search.models import SearchResult


class TestEmbeddings:
    """Tests for embedding providers."""

    def test_get_available_providers(self):
        """Test that available providers include sentence-transformer and ollama."""
        providers = get_available_embedding_providers()
        assert "sentence-transformer" in providers
        assert "ollama" in providers

    def test_get_embeddings_sentence_transformer(self):
        """Test getting sentence-transformer provider."""
        embeddings = get_embeddings("sentence-transformer")
        assert embeddings.provider_name == "sentence-transformer"

    def test_get_embeddings_unknown_raises(self):
        """Test that unknown provider raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_embeddings("unknown_provider")
        assert "unknown_provider" in str(exc_info.value)

    def test_sentence_transformer_provider_name(self):
        """Test SentenceTransformerEmbeddings provider name."""
        embeddings = SentenceTransformerEmbeddings(model="all-MiniLM-L6-v2")
        assert embeddings.provider_name == "sentence-transformer"


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_search_result_properties(self):
        """Test SearchResult property accessors."""
        result = SearchResult(
            chunk_id="chunk_123",
            content="Test content",
            score=0.85,
            metadata={
                "page_title": "Test Page",
                "url": "https://example.com",
                "space_key": "TEST",
                "doc_type": "how-to",
            },
        )

        assert result.page_title == "Test Page"
        assert result.url == "https://example.com"
        assert result.space_key == "TEST"
        assert result.doc_type == "how-to"

    def test_search_result_missing_metadata(self):
        """Test SearchResult with missing metadata fields."""
        result = SearchResult(
            chunk_id="chunk_123",
            content="Test content",
            score=0.85,
            metadata={},
        )

        assert result.page_title == ""
        assert result.url == ""
        assert result.space_key == ""
        assert result.doc_type == ""

    def test_search_result_quality_score(self):
        """Test SearchResult quality_score property."""
        result = SearchResult(
            chunk_id="chunk_123",
            content="Test content",
            score=0.85,
            metadata={"quality_score": 95.5},
        )
        assert result.quality_score == 95.5

    def test_search_result_default_quality_score(self):
        """Test SearchResult default quality_score."""
        result = SearchResult(
            chunk_id="chunk_123",
            content="Test content",
            score=0.85,
            metadata={},
        )
        assert result.quality_score == 100.0
