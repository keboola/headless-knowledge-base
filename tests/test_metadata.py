"""Tests for the metadata module."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from knowledge_base.metadata.extractor import (
    MetadataExtractor,
    db_dict_to_metadata,
    metadata_to_db_dict,
)
from knowledge_base.metadata.normalizer import (
    AUDIENCE_CANONICAL,
    COMPLEXITY_LEVELS,
    DOC_TYPES,
    VocabularyNormalizer,
)
from knowledge_base.metadata.schemas import DocumentMetadata


class TestVocabularyNormalizer:
    """Tests for VocabularyNormalizer."""

    def test_normalize_topics_synonyms(self):
        """Test that topic synonyms are normalized."""
        normalizer = VocabularyNormalizer()
        # "eng" maps to "engineering"
        result = normalizer.normalize_topics(["eng"])
        assert result == ["engineering"]

    def test_normalize_topics_preserves_unknown(self):
        """Test that unknown topics are preserved."""
        normalizer = VocabularyNormalizer()
        result = normalizer.normalize_topics(["custom_topic"])
        assert result == ["custom_topic"]

    def test_normalize_topics_deduplicates(self):
        """Test that duplicate topics are removed."""
        normalizer = VocabularyNormalizer()
        # "eng" and "engineering" both map to "engineering"
        result = normalizer.normalize_topics(["eng", "engineering"])
        assert result == ["engineering"]

    def test_normalize_topics_limits_to_five(self):
        """Test that topics are limited to 5."""
        normalizer = VocabularyNormalizer()
        topics = [f"topic{i}" for i in range(10)]
        result = normalizer.normalize_topics(topics)
        assert len(result) == 5

    def test_normalize_topics_case_insensitive(self):
        """Test that topic normalization is case-insensitive."""
        normalizer = VocabularyNormalizer()
        result = normalizer.normalize_topics(["ENGINEERING", "Engineering", "engineering"])
        assert result == ["engineering"]

    def test_normalize_audience_synonyms(self):
        """Test that audience synonyms are normalized."""
        normalizer = VocabularyNormalizer()
        # "developers" maps to "engineering"
        result = normalizer.normalize_audience(["developers"])
        assert "engineering" in result

    def test_normalize_audience_canonical_pass_through(self):
        """Test that canonical audience values pass through unchanged."""
        normalizer = VocabularyNormalizer()
        result = normalizer.normalize_audience(["all_employees", "engineering"])
        assert result == ["all_employees", "engineering"]

    def test_normalize_audience_deduplicates(self):
        """Test that duplicate audience values are removed."""
        normalizer = VocabularyNormalizer()
        result = normalizer.normalize_audience(["engineers", "developers", "engineering"])
        assert len(result) == 1
        assert result[0] == "engineering"

    def test_normalize_doc_type_valid(self):
        """Test normalization of valid doc types."""
        normalizer = VocabularyNormalizer()
        for doc_type in DOC_TYPES:
            assert normalizer.normalize_doc_type(doc_type) == doc_type

    def test_normalize_doc_type_synonyms(self):
        """Test that doc type synonyms are normalized."""
        normalizer = VocabularyNormalizer()
        assert normalizer.normalize_doc_type("guide") == "how-to"
        assert normalizer.normalize_doc_type("tutorial") == "how-to"
        assert normalizer.normalize_doc_type("documentation") == "reference"
        assert normalizer.normalize_doc_type("faq") == "FAQ"
        assert normalizer.normalize_doc_type("news") == "announcement"

    def test_normalize_doc_type_default(self):
        """Test that unknown doc types default to general."""
        normalizer = VocabularyNormalizer()
        assert normalizer.normalize_doc_type("unknown_type") == "general"

    def test_normalize_complexity_valid(self):
        """Test normalization of valid complexity levels."""
        normalizer = VocabularyNormalizer()
        for level in COMPLEXITY_LEVELS:
            assert normalizer.normalize_complexity(level) == level

    def test_normalize_complexity_synonyms(self):
        """Test that complexity synonyms are normalized."""
        normalizer = VocabularyNormalizer()
        assert normalizer.normalize_complexity("basic") == "beginner"
        assert normalizer.normalize_complexity("easy") == "beginner"
        assert normalizer.normalize_complexity("medium") == "intermediate"
        assert normalizer.normalize_complexity("expert") == "advanced"

    def test_normalize_complexity_default(self):
        """Test that unknown complexity defaults to intermediate."""
        normalizer = VocabularyNormalizer()
        assert normalizer.normalize_complexity("unknown") == "intermediate"


class TestDocumentMetadata:
    """Tests for DocumentMetadata schema."""

    def test_default_values(self):
        """Test that default values are applied."""
        metadata = DocumentMetadata()
        assert metadata.topics == []
        assert metadata.intents == []
        assert metadata.audience == []
        assert metadata.doc_type == "general"
        assert metadata.key_entities == []
        assert metadata.summary == ""
        assert metadata.complexity == "intermediate"

    def test_from_dict_valid(self):
        """Test creating metadata from valid dictionary."""
        data = {
            "topics": ["engineering", "onboarding"],
            "intents": ["learn about tools"],
            "audience": ["new_hires"],
            "doc_type": "how-to",
            "key_entities": ["Slack", "Jira"],
            "summary": "A guide for new engineers",
            "complexity": "beginner",
        }
        metadata = DocumentMetadata.from_dict(data)
        assert metadata.topics == ["engineering", "onboarding"]
        assert metadata.doc_type == "how-to"
        assert metadata.complexity == "beginner"

    def test_from_dict_handles_invalid_types(self):
        """Test that invalid field types are handled gracefully."""
        data = {
            "topics": "not a list",  # Should be list
            "intents": 123,  # Should be list
            "audience": None,  # Should be list
            "doc_type": 456,  # Should be string
            "key_entities": "entity",  # Should be list
            "summary": ["not", "a", "string"],  # Should be string
            "complexity": [],  # Should be string
        }
        metadata = DocumentMetadata.from_dict(data)
        # Should fall back to defaults
        assert metadata.topics == []
        assert metadata.intents == []
        assert metadata.audience == []
        assert metadata.doc_type == "general"
        assert metadata.key_entities == []
        assert metadata.summary == ""
        assert metadata.complexity == "intermediate"


class TestMetadataExtractor:
    """Tests for MetadataExtractor."""

    @pytest.mark.asyncio
    async def test_extract_with_mock_llm(self):
        """Test metadata extraction with mocked LLM."""
        # Create mock LLM
        mock_llm = MagicMock()
        mock_llm.generate_json = AsyncMock(
            return_value={
                "topics": ["engineering", "onboarding"],
                "intents": ["learn the tools"],
                "audience": ["new_hires"],
                "doc_type": "how-to",
                "key_entities": ["Git", "GitHub"],
                "summary": "Guide for setting up development environment",
                "complexity": "beginner",
            }
        )

        extractor = MetadataExtractor(llm=mock_llm)
        metadata = await extractor.extract(
            content="This guide helps new engineers set up their development environment.",
            page_title="Developer Onboarding",
        )

        assert "engineering" in metadata.topics
        assert metadata.doc_type == "how-to"
        assert "new_hires" in metadata.audience
        assert len(metadata.summary) > 0

    @pytest.mark.asyncio
    async def test_extract_handles_llm_error(self):
        """Test that LLM errors are handled gracefully."""
        mock_llm = MagicMock()
        mock_llm.generate_json = AsyncMock(side_effect=Exception("LLM error"))

        extractor = MetadataExtractor(llm=mock_llm)
        metadata = await extractor.extract(
            content="Some content",
            page_title="Test Page",
        )

        # Should return default metadata on error
        assert metadata.doc_type == "general"
        assert metadata.topics == []

    @pytest.mark.asyncio
    async def test_extract_normalizes_output(self):
        """Test that extractor normalizes LLM output."""
        mock_llm = MagicMock()
        mock_llm.generate_json = AsyncMock(
            return_value={
                "topics": ["eng", "dev"],  # Should normalize to engineering
                "intents": ["test"],
                "audience": ["developers"],  # Should normalize to engineering
                "doc_type": "guide",  # Should normalize to how-to
                "key_entities": [],
                "summary": "Test",
                "complexity": "easy",  # Should normalize to beginner
            }
        )

        extractor = MetadataExtractor(llm=mock_llm)
        metadata = await extractor.extract(
            content="Test content",
            page_title="Test",
        )

        assert "engineering" in metadata.topics
        assert metadata.doc_type == "how-to"
        assert metadata.complexity == "beginner"

    @pytest.mark.asyncio
    async def test_extract_truncates_long_content(self):
        """Test that long content is truncated."""
        mock_llm = MagicMock()
        mock_llm.generate_json = AsyncMock(return_value={})

        extractor = MetadataExtractor(llm=mock_llm, max_content_chars=100)
        long_content = "x" * 500

        await extractor.extract(content=long_content, page_title="Test")

        # Check that the prompt was called with truncated content
        call_args = mock_llm.generate_json.call_args[0][0]
        assert len(call_args) < 500 + 500  # Content + prompt template

    @pytest.mark.asyncio
    async def test_extract_batch(self):
        """Test batch extraction."""
        mock_llm = MagicMock()
        mock_llm.generate_json = AsyncMock(
            return_value={
                "topics": ["test"],
                "intents": ["test"],
                "audience": ["all_employees"],
                "doc_type": "general",
                "key_entities": [],
                "summary": "Test summary",
                "complexity": "intermediate",
            }
        )

        extractor = MetadataExtractor(llm=mock_llm)
        items = [
            ("chunk1", "Content 1", "Title 1"),
            ("chunk2", "Content 2", "Title 2"),
            ("chunk3", "Content 3", "Title 3"),
        ]

        results = await extractor.extract_batch(items, concurrency=2)

        assert len(results) == 3
        assert "chunk1" in results
        assert "chunk2" in results
        assert "chunk3" in results
        assert mock_llm.generate_json.call_count == 3


class TestMetadataDbConversion:
    """Tests for database conversion functions."""

    def test_metadata_to_db_dict(self):
        """Test converting metadata to database format."""
        metadata = DocumentMetadata(
            topics=["engineering", "security"],
            intents=["secure code"],
            audience=["engineering"],
            doc_type="policy",
            key_entities=["AWS", "GCP"],
            summary="Security guidelines",
            complexity="advanced",
        )

        db_dict = metadata_to_db_dict(metadata)

        # JSON fields should be serialized
        assert db_dict["topics"] == '["engineering", "security"]'
        assert db_dict["intents"] == '["secure code"]'
        assert db_dict["audience"] == '["engineering"]'
        assert db_dict["key_entities"] == '["AWS", "GCP"]'

        # String fields should remain strings
        assert db_dict["doc_type"] == "policy"
        assert db_dict["summary"] == "Security guidelines"
        assert db_dict["complexity"] == "advanced"

    def test_db_dict_to_metadata(self):
        """Test converting database format to metadata."""
        db_dict = {
            "topics": '["engineering", "security"]',
            "intents": '["secure code"]',
            "audience": '["engineering"]',
            "doc_type": "policy",
            "key_entities": '["AWS", "GCP"]',
            "summary": "Security guidelines",
            "complexity": "advanced",
        }

        metadata = db_dict_to_metadata(db_dict)

        assert metadata.topics == ["engineering", "security"]
        assert metadata.intents == ["secure code"]
        assert metadata.audience == ["engineering"]
        assert metadata.doc_type == "policy"
        assert metadata.key_entities == ["AWS", "GCP"]
        assert metadata.summary == "Security guidelines"
        assert metadata.complexity == "advanced"

    def test_roundtrip_conversion(self):
        """Test that metadata survives roundtrip conversion."""
        original = DocumentMetadata(
            topics=["finance", "policy"],
            intents=["expense reporting"],
            audience=["all_employees", "finance"],
            doc_type="policy",
            key_entities=["Expensify", "Finance Team"],
            summary="Expense reporting procedures",
            complexity="beginner",
        )

        db_dict = metadata_to_db_dict(original)
        restored = db_dict_to_metadata(db_dict)

        assert restored.topics == original.topics
        assert restored.intents == original.intents
        assert restored.audience == original.audience
        assert restored.doc_type == original.doc_type
        assert restored.key_entities == original.key_entities
        assert restored.summary == original.summary
        assert restored.complexity == original.complexity
