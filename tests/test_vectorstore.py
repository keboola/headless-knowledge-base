"""Tests for the vectorstore module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Check if chromadb is available
try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not CHROMADB_AVAILABLE,
    reason="chromadb not installed"
)

if CHROMADB_AVAILABLE:
    from knowledge_base.vectorstore.embeddings import (
        BaseEmbeddings,
        SentenceTransformerEmbeddings,
        get_embeddings,
        get_available_embedding_providers,
    )
    from knowledge_base.vectorstore.client import ChromaClient
    from knowledge_base.vectorstore.retriever import VectorRetriever, SearchResult


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


class TestChromaClient:
    """Tests for ChromaDB client."""

    def test_init_defaults(self):
        """Test default initialization."""
        client = ChromaClient()
        assert client.host == "chromadb"
        assert client.port == 8000
        assert client.use_ssl is True  # Default is True for secure connections
        assert client.token == ""
        assert client.collection_name == "confluence_documents"

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        client = ChromaClient(
            host="localhost",
            port=9000,
            collection_name="test_collection",
        )
        assert client.host == "localhost"
        assert client.port == 9000
        assert client.collection_name == "test_collection"

    def test_init_with_ssl(self):
        """Test initialization with SSL enabled."""
        client = ChromaClient(
            host="chromadb.example.com",
            port=443,
            use_ssl=True,
        )
        assert client.host == "chromadb.example.com"
        assert client.port == 443
        assert client.use_ssl is True

    def test_init_with_token(self):
        """Test initialization with authentication token."""
        client = ChromaClient(
            host="chromadb.example.com",
            port=443,
            use_ssl=True,
            token="test-token-12345",
        )
        assert client.token == "test-token-12345"
        assert client.use_ssl is True

    def test_init_ssl_and_token_for_cloud_run(self):
        """Test Cloud Run configuration pattern (SSL + token + port 443)."""
        # This simulates the Cloud Run deployment pattern
        client = ChromaClient(
            host="chromadb-abc123-uc.a.run.app",
            port=443,
            use_ssl=True,
            token="secret-chromadb-token",
            collection_name="confluence_documents",
        )
        assert client.host == "chromadb-abc123-uc.a.run.app"
        assert client.port == 443
        assert client.use_ssl is True
        assert client.token == "secret-chromadb-token"


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


class TestVectorRetriever:
    """Tests for VectorRetriever."""

    @pytest.mark.asyncio
    async def test_search_with_mock(self):
        """Test search with mocked dependencies."""
        # Mock embeddings
        mock_embeddings = MagicMock()
        mock_embeddings.embed_single = AsyncMock(return_value=[0.1] * 384)

        # Mock ChromaDB client
        mock_chroma = MagicMock()
        mock_chroma.query = AsyncMock(return_value={
            "ids": [["chunk_1", "chunk_2"]],
            "documents": [["Content 1", "Content 2"]],
            "metadatas": [[{"page_title": "Page 1"}, {"page_title": "Page 2"}]],
            "distances": [[0.1, 0.2]],
        })

        retriever = VectorRetriever(embeddings=mock_embeddings, chroma=mock_chroma)
        results = await retriever.search("test query", n_results=2)

        assert len(results) == 2
        assert results[0].chunk_id == "chunk_1"
        assert results[0].content == "Content 1"
        assert results[1].chunk_id == "chunk_2"

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        """Test search returning empty results."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_single = AsyncMock(return_value=[0.1] * 384)

        mock_chroma = MagicMock()
        mock_chroma.query = AsyncMock(return_value={
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        })

        retriever = VectorRetriever(embeddings=mock_embeddings, chroma=mock_chroma)
        results = await retriever.search("test query")

        assert len(results) == 0

    def test_build_filter_space_key(self):
        """Test building filter with space_key."""
        retriever = VectorRetriever()
        filter_dict = retriever._build_filter(space_key="ENG")
        assert filter_dict == {"space_key": {"$eq": "ENG"}}

    def test_build_filter_doc_type(self):
        """Test building filter with doc_type."""
        retriever = VectorRetriever()
        filter_dict = retriever._build_filter(doc_type="how-to")
        assert filter_dict == {"doc_type": {"$eq": "how-to"}}

    def test_build_filter_combined(self):
        """Test building filter with multiple conditions."""
        retriever = VectorRetriever()
        filter_dict = retriever._build_filter(space_key="ENG", doc_type="how-to")
        assert filter_dict == {
            "$and": [
                {"space_key": {"$eq": "ENG"}},
                {"doc_type": {"$eq": "how-to"}},
            ]
        }

    def test_build_filter_none(self):
        """Test building filter with no conditions."""
        retriever = VectorRetriever()
        filter_dict = retriever._build_filter()
        assert filter_dict is None
