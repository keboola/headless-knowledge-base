"""Build and manage the knowledge graph using Graphiti.

This module provides a Graphiti-based graph builder that is the primary
storage layer for the knowledge base (ChromaDB has been eliminated).

Key features:
- Uses Graphiti's add_episode() for document/chunk ingestion
- Stores all 25 metadata fields as JSON in source_description
- Supports bi-temporal metadata (event_time = page.updated_at)
- Persists to Kuzu (dev) or Neo4j (prod)
- Provides quality score updates for feedback system
- Keeps EntityResolver as post-processing layer for domain-specific aliases
"""

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from knowledge_base.config import settings
from knowledge_base.graph.entity_extractor import EntityResolver
from knowledge_base.graph.entity_schemas import (
    DocumentEntity,
    GraphEntityType,
    GraphRelationType,
    PersonEntity,
    TeamEntity,
    TopicEntity,
)
from knowledge_base.graph.graphiti_client import get_graphiti_client, GraphitiClientError
from knowledge_base.graph.models import ExtractedEntity, EntityType

if TYPE_CHECKING:
    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType
    from knowledge_base.vectorstore.indexer import ChunkData

logger = logging.getLogger(__name__)


class GraphitiBuilder:
    """Build and maintain a knowledge graph using Graphiti.

    This provides the same interface as KnowledgeGraphBuilder but uses
    Graphiti + Kuzu/Neo4j instead of NetworkX + SQLite.
    """

    def __init__(self, group_id: str | None = None):
        """Initialize the Graphiti builder.

        Args:
            group_id: Graphiti group ID for multi-tenancy (defaults to settings)
        """
        self.group_id = group_id or settings.GRAPH_GROUP_ID
        self.client = get_graphiti_client()
        self.resolver = EntityResolver()  # Keep for domain-specific alias logic
        self._graphiti: "Graphiti | None" = None

    async def _get_graphiti(self) -> "Graphiti":
        """Get the Graphiti instance lazily."""
        if self._graphiti is None:
            self._graphiti = await self.client.get_client()
        return self._graphiti

    async def process_document(
        self,
        page_id: str,
        content: str,
        title: str | None = None,
        author: str | None = None,
        space_key: str | None = None,
        url: str | None = None,
        topics: list[str] | None = None,
        updated_at: datetime | None = None,
        chunk_id: str | None = None,
        chunk_index: int | None = None,
    ) -> dict[str, Any]:
        """Process a document and add to knowledge graph via Graphiti.

        Uses Graphiti's add_episode() which handles:
        - Entity extraction using LLM
        - Relationship inference
        - Bi-temporal tracking
        - Incremental updates

        Args:
            page_id: Document page ID
            content: Document content
            title: Document title
            author: Document author (optional)
            space_key: Confluence space key (optional)
            url: Document URL (optional)
            topics: Document topics from metadata (optional)
            updated_at: When the document was last updated (for bi-temporal)
            chunk_id: Specific chunk ID for chunk-level linking
            chunk_index: Chunk index within the page

        Returns:
            Dict with processing results (entities found, relationships created)
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            logger.debug("Graphiti disabled, skipping document processing")
            return {"skipped": True, "reason": "graphiti_disabled"}

        if not content or not content.strip():
            logger.debug(f"Empty content for {page_id}, skipping")
            return {"skipped": True, "reason": "empty_content"}

        try:
            graphiti = await self._get_graphiti()

            # Build episode metadata
            # event_time = when the document was updated (real-world time)
            event_time = updated_at or datetime.utcnow()

            # Build source reference for traceability
            source_description = self._build_source_description(
                page_id=page_id,
                title=title,
                space_key=space_key,
                url=url,
                chunk_id=chunk_id,
                chunk_index=chunk_index,
            )

            # Add as episode - Graphiti handles entity extraction internally
            episode = await graphiti.add_episode(
                name=title or f"Document {page_id}",
                episode_body=content,
                source_description=source_description,
                reference_time=event_time,
                group_id=self.group_id,
            )

            # Post-process with our EntityResolver for domain-specific aliases
            # This preserves existing alias logic during migration
            if author:
                await self._add_author_relationship(graphiti, page_id, author, event_time)

            if space_key:
                await self._add_space_relationship(graphiti, page_id, space_key, event_time)

            if topics:
                await self._add_topic_relationships(graphiti, page_id, topics, event_time)

            # add_episode returns AddEpisodeResults which has .episode (EpisodicNode)
            episode_uuid = episode.episode.uuid if hasattr(episode, 'episode') else getattr(episode, 'uuid', 'unknown')
            logger.info(f"Processed document {page_id} with Graphiti (episode: {episode_uuid})")

            return {
                "success": True,
                "page_id": page_id,
                "episode_id": str(episode_uuid),
                "event_time": event_time.isoformat(),
            }

        except GraphitiClientError as e:
            logger.error(f"Graphiti client error processing {page_id}: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Failed to process document {page_id} with Graphiti: {e}")
            return {"success": False, "error": str(e)}

    def _build_source_description(
        self,
        page_id: str,
        title: str | None = None,
        space_key: str | None = None,
        url: str | None = None,
        chunk_id: str | None = None,
        chunk_index: int | None = None,
    ) -> str:
        """Build a source description for Graphiti episode.

        This provides context about where the information came from.
        """
        parts = []

        if title:
            parts.append(f"Title: {title}")
        if space_key:
            parts.append(f"Space: {space_key}")
        if url:
            parts.append(f"URL: {url}")
        if chunk_id:
            parts.append(f"Chunk: {chunk_id}")
            if chunk_index is not None:
                parts.append(f"Section: {chunk_index + 1}")

        parts.append(f"Page ID: {page_id}")

        return " | ".join(parts)

    async def _add_author_relationship(
        self,
        graphiti: "Graphiti",
        page_id: str,
        author: str,
        event_time: datetime,
    ) -> None:
        """Add author relationship to the graph.

        This ensures author information is captured even if not extracted by LLM.
        """
        try:
            # Add a small episode noting the authorship
            await graphiti.add_episode(
                name=f"Author of {page_id}",
                episode_body=f"The document {page_id} was authored by {author}.",
                source_description=f"Authorship metadata for page {page_id}",
                reference_time=event_time,
                group_id=self.group_id,
            )
        except Exception as e:
            logger.warning(f"Failed to add author relationship for {page_id}: {e}")

    async def _add_space_relationship(
        self,
        graphiti: "Graphiti",
        page_id: str,
        space_key: str,
        event_time: datetime,
    ) -> None:
        """Add space/team relationship to the graph."""
        try:
            await graphiti.add_episode(
                name=f"Space for {page_id}",
                episode_body=f"The document {page_id} belongs to the {space_key} space.",
                source_description=f"Space metadata for page {page_id}",
                reference_time=event_time,
                group_id=self.group_id,
            )
        except Exception as e:
            logger.warning(f"Failed to add space relationship for {page_id}: {e}")

    async def _add_topic_relationships(
        self,
        graphiti: "Graphiti",
        page_id: str,
        topics: list[str],
        event_time: datetime,
    ) -> None:
        """Add topic relationships to the graph."""
        if not topics:
            return

        try:
            topics_str = ", ".join(topics)
            await graphiti.add_episode(
                name=f"Topics for {page_id}",
                episode_body=f"The document {page_id} covers these topics: {topics_str}.",
                source_description=f"Topic metadata for page {page_id}",
                reference_time=event_time,
                group_id=self.group_id,
            )
        except Exception as e:
            logger.warning(f"Failed to add topic relationships for {page_id}: {e}")

    async def process_chunk(
        self,
        chunk_id: str,
        content: str,
        page_id: str,
        page_title: str,
        chunk_index: int,
        **metadata,
    ) -> dict[str, Any]:
        """Process a single chunk and add to the graph.

        This enables chunk-level entity linking (not just page-level).

        Args:
            chunk_id: Unique chunk identifier
            content: Chunk content
            page_id: Parent page ID
            page_title: Parent page title
            chunk_index: Index of chunk within page
            **metadata: Additional metadata (author, space_key, url, etc.)

        Returns:
            Processing result dict
        """
        return await self.process_document(
            page_id=page_id,
            content=content,
            title=f"{page_title} (Section {chunk_index + 1})",
            chunk_id=chunk_id,
            chunk_index=chunk_index,
            **metadata,
        )

    async def search_entities(
        self,
        query: str,
        entity_types: list[GraphEntityType] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search for entities in the graph.

        Args:
            query: Search query
            entity_types: Filter by entity types (optional)
            limit: Maximum results

        Returns:
            List of matching entity dicts
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            return []

        try:
            graphiti = await self._get_graphiti()

            # Use Graphiti's search
            results = await graphiti.search(
                query=query,
                num_results=limit,
                group_ids=[self.group_id],
            )

            # Convert to standardized format
            entities = []
            for result in results:
                entities.append({
                    "entity_id": str(result.uuid) if hasattr(result, 'uuid') else str(result),
                    "name": result.name if hasattr(result, 'name') else str(result),
                    "score": result.score if hasattr(result, 'score') else 1.0,
                    "source": "graphiti",
                })

            return entities

        except Exception as e:
            logger.error(f"Entity search failed: {e}")
            return []

    async def get_related_documents(
        self,
        page_id: str,
        max_results: int = 10,
    ) -> list[str]:
        """Get related documents via graph traversal.

        Same interface as KnowledgeGraphBuilder.get_related_documents()

        Args:
            page_id: Starting document page ID
            max_results: Maximum documents to return

        Returns:
            List of related page IDs
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            return []

        try:
            graphiti = await self._get_graphiti()

            # Search for episodes related to this page
            results = await graphiti.search(
                query=f"page:{page_id}",
                num_results=max_results * 2,  # Get extra for filtering
                group_ids=[self.group_id],
            )

            # Extract unique page IDs from results
            related_pages = set()
            for result in results:
                # Parse source_description to extract page IDs
                if hasattr(result, 'source_description'):
                    source = result.source_description
                    if 'Page ID:' in source:
                        # Extract page ID from source description
                        parts = source.split('Page ID:')
                        if len(parts) > 1:
                            related_page = parts[1].strip().split()[0]
                            if related_page != page_id:
                                related_pages.add(related_page)

            return list(related_pages)[:max_results]

        except Exception as e:
            logger.error(f"Failed to get related documents for {page_id}: {e}")
            return []

    async def get_stats(self) -> dict[str, Any]:
        """Get graph statistics.

        Returns:
            Statistics dictionary
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            return {"enabled": False}

        try:
            graphiti = await self._get_graphiti()

            # Note: Graphiti may have different stats API
            # This is a placeholder that should be updated based on actual API
            return {
                "enabled": True,
                "backend": settings.GRAPH_BACKEND,
                "group_id": self.group_id,
            }

        except Exception as e:
            logger.error(f"Failed to get graph stats: {e}")
            return {"enabled": True, "error": str(e)}

    # =========================================================================
    # New methods for Graphiti-only architecture (ChromaDB eliminated)
    # =========================================================================

    async def add_chunk_episode(
        self,
        chunk_data: "ChunkData | dict[str, Any]",
        event_time: datetime | None = None,
    ) -> dict[str, Any]:
        """Add a chunk as a Graphiti episode with full metadata.

        This stores all 25 metadata fields as JSON in the source_description,
        making Graphiti the single source of truth (replacing ChromaDB).

        Args:
            chunk_data: ChunkData object or dict with chunk information
            event_time: When the content was valid (defaults to updated_at or now)

        Returns:
            Dict with success status and episode UUID
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            logger.debug("Graphiti disabled, skipping chunk episode")
            return {"success": False, "skipped": True, "reason": "graphiti_disabled"}

        try:
            # Convert ChunkData to dict if needed
            if hasattr(chunk_data, 'to_metadata'):
                metadata = chunk_data.to_metadata()
                chunk_id = chunk_data.chunk_id
                content = chunk_data.content
                page_title = chunk_data.page_title
                updated_at = chunk_data.updated_at
            else:
                # Assume it's already a dict
                metadata = dict(chunk_data)
                chunk_id = metadata.get('chunk_id', '')
                content = metadata.pop('content', '')
                page_title = metadata.get('page_title', '')
                updated_at = metadata.get('updated_at', '')

            if not content or not content.strip():
                logger.debug(f"Empty content for chunk {chunk_id}, skipping")
                return {"success": False, "skipped": True, "reason": "empty_content"}

            # Add chunk_id to metadata for retrieval
            metadata['chunk_id'] = chunk_id

            graphiti = await self._get_graphiti()

            # Determine event time (bi-temporal: when the content was valid)
            if event_time:
                ref_time = event_time
            elif updated_at:
                try:
                    ref_time = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    ref_time = datetime.utcnow()
            else:
                ref_time = datetime.utcnow()

            # Store all metadata as JSON in source_description
            source_description = json.dumps(metadata, default=str)

            # Add episode with chunk_id as name for easy lookup
            episode = await graphiti.add_episode(
                name=chunk_id,  # Use chunk_id as episode name for retrieval
                episode_body=content,
                source_description=source_description,
                reference_time=ref_time,
                group_id=self.group_id,
            )

            # add_episode returns AddEpisodeResults which has .episode (EpisodicNode)
            episode_uuid = episode.episode.uuid if hasattr(episode, 'episode') else getattr(episode, 'uuid', 'unknown')
            logger.debug(f"Added chunk episode: {chunk_id} -> {episode_uuid}")

            return {
                "success": True,
                "chunk_id": chunk_id,
                "episode_uuid": str(episode_uuid),
                "event_time": ref_time.isoformat(),
            }

        except GraphitiClientError as e:
            logger.error(f"Graphiti client error adding chunk {chunk_id}: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Failed to add chunk episode {chunk_id}: {e}")
            return {"success": False, "error": str(e)}

    async def get_chunk_episode(self, chunk_id: str) -> dict[str, Any] | None:
        """Get a chunk episode by chunk_id.

        Args:
            chunk_id: The chunk ID to look up

        Returns:
            Dict with episode data and parsed metadata, or None if not found
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            return None

        try:
            graphiti = await self._get_graphiti()

            # Search for episode by chunk_id (stored as name)
            results = await graphiti.search(
                query=chunk_id,
                num_results=5,
                group_ids=[self.group_id],
            )

            # Find exact match by name
            for result in results:
                if hasattr(result, 'name') and result.name == chunk_id:
                    # Parse metadata from source_description
                    metadata = {}
                    if hasattr(result, 'source_description') and result.source_description:
                        try:
                            metadata = json.loads(result.source_description)
                        except json.JSONDecodeError:
                            pass

                    return {
                        "chunk_id": chunk_id,
                        "episode_uuid": str(result.uuid) if hasattr(result, 'uuid') else None,
                        "content": result.content if hasattr(result, 'content') else None,
                        "metadata": metadata,
                    }

            return None

        except Exception as e:
            logger.error(f"Failed to get chunk episode {chunk_id}: {e}")
            return None

    async def get_chunk_quality_score(self, chunk_id: str) -> float | None:
        """Get the quality score for a chunk.

        Args:
            chunk_id: The chunk ID to look up

        Returns:
            Quality score (0-100) or None if not found
        """
        episode = await self.get_chunk_episode(chunk_id)
        if episode and episode.get('metadata'):
            return episode['metadata'].get('quality_score')
        return None

    async def update_chunk_quality(
        self,
        chunk_id: str,
        new_score: float,
        increment_feedback_count: bool = True,
    ) -> bool:
        """Update the quality score for a chunk in Graphiti.

        This updates the metadata stored in the episode's source_description.

        Args:
            chunk_id: The chunk ID to update
            new_score: New quality score (0-100)
            increment_feedback_count: Whether to increment feedback_count

        Returns:
            True if successful, False otherwise
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            logger.debug("Graphiti disabled, skipping quality update")
            return False

        try:
            # Get current episode
            episode = await self.get_chunk_episode(chunk_id)
            if not episode:
                logger.warning(f"Chunk {chunk_id} not found for quality update")
                return False

            # Update metadata
            metadata = episode.get('metadata', {})
            metadata['quality_score'] = max(0.0, min(100.0, new_score))

            if increment_feedback_count:
                current_count = metadata.get('feedback_count', 0)
                metadata['feedback_count'] = current_count + 1

            # Re-add episode with updated metadata
            # (Graphiti doesn't have direct update, so we use add_episode which upserts)
            graphiti = await self._get_graphiti()

            content = episode.get('content', '')
            if not content:
                logger.warning(f"No content found for chunk {chunk_id}, cannot update")
                return False

            # Determine reference time from metadata
            updated_at = metadata.get('updated_at', '')
            try:
                ref_time = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                ref_time = datetime.utcnow()

            await graphiti.add_episode(
                name=chunk_id,
                episode_body=content,
                source_description=json.dumps(metadata, default=str),
                reference_time=ref_time,
                group_id=self.group_id,
            )

            logger.debug(f"Updated quality score for {chunk_id}: {new_score}")
            return True

        except Exception as e:
            logger.error(f"Failed to update quality for {chunk_id}: {e}")
            return False

    async def update_chunk_metadata(
        self,
        chunk_id: str,
        metadata_updates: dict[str, Any],
    ) -> bool:
        """Update metadata for a chunk in Graphiti.

        Args:
            chunk_id: The chunk ID to update
            metadata_updates: Dict of metadata fields to update

        Returns:
            True if successful, False otherwise
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            return False

        try:
            # Get current episode
            episode = await self.get_chunk_episode(chunk_id)
            if not episode:
                logger.warning(f"Chunk {chunk_id} not found for metadata update")
                return False

            # Merge updates into existing metadata
            metadata = episode.get('metadata', {})
            metadata.update(metadata_updates)

            # Re-add episode with updated metadata
            graphiti = await self._get_graphiti()

            content = episode.get('content', '')
            if not content:
                logger.warning(f"No content found for chunk {chunk_id}, cannot update metadata")
                return False

            # Determine reference time from metadata
            updated_at = metadata.get('updated_at', '')
            try:
                ref_time = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                ref_time = datetime.utcnow()

            await graphiti.add_episode(
                name=chunk_id,
                episode_body=content,
                source_description=json.dumps(metadata, default=str),
                reference_time=ref_time,
                group_id=self.group_id,
            )

            logger.debug(f"Updated metadata for {chunk_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to update metadata for {chunk_id}: {e}")
            return False

    async def delete_chunk_episode(self, chunk_id: str) -> bool:
        """Delete a chunk episode from Graphiti.

        Args:
            chunk_id: The chunk ID to delete

        Returns:
            True if successful, False otherwise
        """
        if not settings.GRAPH_ENABLE_GRAPHITI:
            return False

        try:
            graphiti = await self._get_graphiti()

            # Note: Graphiti may not have direct delete by name
            # This is a placeholder - implementation depends on Graphiti API
            # For now, we can mark as deleted by setting a flag in metadata
            episode = await self.get_chunk_episode(chunk_id)
            if episode and episode.get('metadata'):
                metadata = episode['metadata']
                metadata['deleted'] = True
                metadata['deleted_at'] = datetime.utcnow().isoformat()

                await graphiti.add_episode(
                    name=chunk_id,
                    episode_body="[DELETED]",
                    source_description=json.dumps(metadata, default=str),
                    reference_time=datetime.utcnow(),
                    group_id=self.group_id,
                )
                logger.info(f"Marked chunk {chunk_id} as deleted")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to delete chunk {chunk_id}: {e}")
            return False

    async def close(self) -> None:
        """Close the Graphiti connection."""
        await self.client.close()
        self._graphiti = None


# Factory function for getting a builder instance
_default_builder: GraphitiBuilder | None = None


def get_graphiti_builder() -> GraphitiBuilder:
    """Get the default GraphitiBuilder instance.

    Returns:
        GraphitiBuilder configured from settings
    """
    global _default_builder
    if _default_builder is None:
        _default_builder = GraphitiBuilder()
    return _default_builder
