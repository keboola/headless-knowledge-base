"""LLM-based metadata extraction."""

import asyncio
import json
import logging
from typing import Any

from knowledge_base.config import settings
from knowledge_base.metadata.normalizer import VocabularyNormalizer
from knowledge_base.metadata.schemas import DocumentMetadata
from knowledge_base.rag.llm import BaseLLM

logger = logging.getLogger(__name__)

# Metadata extraction prompt template
METADATA_EXTRACTION_PROMPT = """Analyze this Confluence document and extract structured metadata.

Title: {title}
Content: {content}

Extract as JSON:
{{
    "topics": ["3-5 main topics covered in this document"],
    "intents": ["2-3 use cases when this document would be useful"],
    "audience": ["who should read this - e.g., all_employees, engineering, sales, hr, new_hires, managers"],
    "doc_type": "one of: policy, how-to, reference, FAQ, announcement, meeting-notes, general",
    "key_entities": ["specific products, services, tools, locations, or systems mentioned"],
    "summary": "1-2 sentence summary of what this document is about",
    "complexity": "one of: beginner, intermediate, advanced"
}}

Be specific with topics and entities. For audience, use canonical values like "all_employees", "engineering", "new_hires", etc."""


class MetadataExtractor:
    """Extract metadata from document chunks using LLM."""

    def __init__(
        self,
        llm: BaseLLM,
        normalizer: VocabularyNormalizer | None = None,
        max_content_chars: int = 4000,
    ):
        """
        Initialize the metadata extractor.

        Args:
            llm: LLM client for generation
            normalizer: Vocabulary normalizer (created if not provided)
            max_content_chars: Maximum characters of content to send to LLM
        """
        self.llm = llm
        self.normalizer = normalizer or VocabularyNormalizer()
        self.max_content_chars = max_content_chars

    async def extract(self, content: str, page_title: str) -> DocumentMetadata:
        """
        Extract metadata from a chunk of content.

        Args:
            content: The text content to analyze
            page_title: Title of the source page for context

        Returns:
            DocumentMetadata with extracted and normalized values
        """
        # Truncate content if needed
        truncated_content = content[: self.max_content_chars]
        if len(content) > self.max_content_chars:
            truncated_content += "..."

        # Build prompt
        prompt = METADATA_EXTRACTION_PROMPT.format(
            title=page_title,
            content=truncated_content,
        )

        # Generate metadata using LLM
        try:
            raw_metadata = await self.llm.generate_json(prompt)
        except Exception as e:
            logger.error(f"LLM extraction failed for '{page_title}': {e}")
            raw_metadata = {}

        # Parse and normalize the response
        return self._normalize_metadata(raw_metadata)

    def _normalize_metadata(self, raw: dict[str, Any]) -> DocumentMetadata:
        """Normalize raw LLM output to canonical forms."""
        # Get raw values with defaults
        raw_topics = raw.get("topics", [])
        raw_intents = raw.get("intents", [])
        raw_audience = raw.get("audience", [])
        raw_doc_type = raw.get("doc_type", "general")
        raw_key_entities = raw.get("key_entities", [])
        raw_summary = raw.get("summary", "")
        raw_complexity = raw.get("complexity", "intermediate")

        # Ensure lists are actually lists
        if not isinstance(raw_topics, list):
            raw_topics = []
        if not isinstance(raw_intents, list):
            raw_intents = []
        if not isinstance(raw_audience, list):
            raw_audience = []
        if not isinstance(raw_key_entities, list):
            raw_key_entities = []
        if not isinstance(raw_summary, str):
            raw_summary = ""
        if not isinstance(raw_doc_type, str):
            raw_doc_type = "general"
        if not isinstance(raw_complexity, str):
            raw_complexity = "intermediate"

        # Normalize values
        normalized_topics = self.normalizer.normalize_topics(raw_topics)
        normalized_audience = self.normalizer.normalize_audience(raw_audience)
        normalized_doc_type = self.normalizer.normalize_doc_type(raw_doc_type)
        normalized_complexity = self.normalizer.normalize_complexity(raw_complexity)

        # Clean up intents and entities (just strip whitespace)
        cleaned_intents = [i.strip() for i in raw_intents if isinstance(i, str) and i.strip()][:3]
        cleaned_entities = [e.strip() for e in raw_key_entities if isinstance(e, str) and e.strip()][:10]

        return DocumentMetadata(
            topics=normalized_topics,
            intents=cleaned_intents,
            audience=normalized_audience,
            doc_type=normalized_doc_type,
            key_entities=cleaned_entities,
            summary=raw_summary.strip()[:500],  # Limit summary length
            complexity=normalized_complexity,
        )

    async def extract_batch(
        self,
        items: list[tuple[str, str, str]],
        concurrency: int | None = None,
    ) -> dict[str, DocumentMetadata]:
        """
        Extract metadata for multiple chunks in parallel.

        Args:
            items: List of (chunk_id, content, page_title) tuples
            concurrency: Max concurrent extractions (defaults to METADATA_BATCH_SIZE)

        Returns:
            Dictionary mapping chunk_id to DocumentMetadata
        """
        concurrency = concurrency or settings.METADATA_BATCH_SIZE
        semaphore = asyncio.Semaphore(concurrency)
        results: dict[str, DocumentMetadata] = {}

        async def process_item(chunk_id: str, content: str, page_title: str) -> None:
            async with semaphore:
                try:
                    metadata = await self.extract(content, page_title)
                    results[chunk_id] = metadata
                    logger.debug(f"Extracted metadata for chunk {chunk_id}")
                except Exception as e:
                    logger.error(f"Failed to extract metadata for chunk {chunk_id}: {e}")
                    # Store default metadata on failure
                    results[chunk_id] = DocumentMetadata()

        # Create tasks for all items
        tasks = [
            asyncio.create_task(process_item(chunk_id, content, page_title))
            for chunk_id, content, page_title in items
        ]

        # Wait for all to complete
        await asyncio.gather(*tasks, return_exceptions=True)

        return results


def metadata_to_db_dict(metadata: DocumentMetadata) -> dict[str, Any]:
    """
    Convert DocumentMetadata to dictionary for database storage.

    JSON fields are serialized to strings for SQLite storage.
    """
    return {
        "topics": json.dumps(metadata.topics),
        "intents": json.dumps(metadata.intents),
        "audience": json.dumps(metadata.audience),
        "doc_type": metadata.doc_type,
        "key_entities": json.dumps(metadata.key_entities),
        "summary": metadata.summary,
        "complexity": metadata.complexity,
    }


def db_dict_to_metadata(data: dict[str, Any]) -> DocumentMetadata:
    """
    Convert database dictionary to DocumentMetadata.

    JSON fields are deserialized from strings.
    """
    return DocumentMetadata(
        topics=json.loads(data.get("topics", "[]")),
        intents=json.loads(data.get("intents", "[]")),
        audience=json.loads(data.get("audience", "[]")),
        doc_type=data.get("doc_type", "general"),
        key_entities=json.loads(data.get("key_entities", "[]")),
        summary=data.get("summary", ""),
        complexity=data.get("complexity", "intermediate"),
    )
