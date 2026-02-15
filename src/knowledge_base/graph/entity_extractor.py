"""Entity resolution for knowledge graph construction."""

import logging

from knowledge_base.graph.models import ExtractedEntity

logger = logging.getLogger(__name__)


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
