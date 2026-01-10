"""LLM-based entity extraction for knowledge graph construction."""

import json
import logging
from typing import TYPE_CHECKING

from knowledge_base.graph.models import ExtractedEntities, ExtractedEntity, EntityType

if TYPE_CHECKING:
    from knowledge_base.rag.llm import BaseLLM

logger = logging.getLogger(__name__)

ENTITY_EXTRACTION_PROMPT = """Extract entities from this document.

Content:
{content}

Extract as JSON:
{{
    "people": ["full names mentioned"],
    "teams": ["team or department names"],
    "products": ["products, services, tools"],
    "locations": ["offices, cities, regions"]
}}

Only include clearly mentioned entities, not inferred ones.
Return valid JSON only, no markdown formatting."""


class EntityExtractor:
    """Extract entities from document content using LLM."""

    def __init__(self, llm: "BaseLLM", max_content_length: int = 8000):
        """Initialize entity extractor.

        Args:
            llm: LLM instance for entity extraction
            max_content_length: Maximum content length to process
        """
        self.llm = llm
        self.max_content_length = max_content_length

    async def extract(self, content: str) -> ExtractedEntities:
        """Extract entities from document content.

        Args:
            content: Document content to extract entities from

        Returns:
            ExtractedEntities with people, teams, products, locations
        """
        if not content or not content.strip():
            return ExtractedEntities()

        # Truncate if too long
        if len(content) > self.max_content_length:
            content = content[: self.max_content_length] + "..."
            logger.debug(f"Content truncated to {self.max_content_length} chars")

        prompt = ENTITY_EXTRACTION_PROMPT.format(content=content)

        try:
            response = await self.llm.generate_json(prompt)

            if not response:
                logger.warning("LLM returned empty response for entity extraction")
                return ExtractedEntities()

            return ExtractedEntities(
                people=self._clean_list(response.get("people", [])),
                teams=self._clean_list(response.get("teams", [])),
                products=self._clean_list(response.get("products", [])),
                locations=self._clean_list(response.get("locations", [])),
            )

        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return ExtractedEntities()

    def _clean_list(self, items: list) -> list[str]:
        """Clean and deduplicate entity list."""
        if not isinstance(items, list):
            return []

        cleaned = []
        seen = set()

        for item in items:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if not item:
                continue
            # Normalize for deduplication
            normalized = item.lower()
            if normalized not in seen:
                seen.add(normalized)
                cleaned.append(item)

        return cleaned

    async def extract_batch(
        self, documents: list[dict[str, str]]
    ) -> dict[str, ExtractedEntities]:
        """Extract entities from multiple documents.

        Args:
            documents: List of dicts with 'page_id' and 'content' keys

        Returns:
            Dict mapping page_id to ExtractedEntities
        """
        results = {}

        for doc in documents:
            page_id = doc.get("page_id", "")
            content = doc.get("content", "")

            if page_id and content:
                entities = await self.extract(content)
                results[page_id] = entities
                logger.debug(
                    f"Extracted from {page_id}: "
                    f"{len(entities.people)} people, {len(entities.teams)} teams, "
                    f"{len(entities.products)} products, {len(entities.locations)} locations"
                )

        return results


class EntityResolver:
    """Resolve entity names to canonical forms."""

    def __init__(self):
        """Initialize entity resolver with alias mappings."""
        # Common aliases for entity resolution
        self._aliases: dict[str, str] = {}

    def add_alias(self, alias: str, canonical: str) -> None:
        """Add an alias mapping."""
        self._aliases[alias.lower()] = canonical

    def resolve(self, entity: ExtractedEntity) -> ExtractedEntity:
        """Resolve entity to canonical form.

        Args:
            entity: Entity to resolve

        Returns:
            Entity with canonical name (may be same as input)
        """
        normalized = entity.name.lower()

        if normalized in self._aliases:
            canonical_name = self._aliases[normalized]
            return ExtractedEntity(
                name=canonical_name,
                entity_type=entity.entity_type,
                aliases=[entity.name] if entity.name != canonical_name else [],
                context=entity.context,
            )

        return entity

    def resolve_all(self, entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
        """Resolve all entities to canonical forms.

        Also merges entities with same canonical name.
        """
        resolved_map: dict[str, ExtractedEntity] = {}

        for entity in entities:
            resolved = self.resolve(entity)
            entity_id = resolved.entity_id

            if entity_id in resolved_map:
                # Merge aliases
                existing = resolved_map[entity_id]
                all_aliases = set(existing.aliases) | set(resolved.aliases)
                if entity.name != resolved.name:
                    all_aliases.add(entity.name)
                existing.aliases = list(all_aliases)
            else:
                resolved_map[entity_id] = resolved

        return list(resolved_map.values())
