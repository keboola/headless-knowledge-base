"""Query the knowledge graph for related context."""

import logging
from typing import TYPE_CHECKING

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_base.db.models import Entity as EntityModel
from knowledge_base.db.models import Relationship as RelationshipModel
from knowledge_base.db.models import RawPage

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class GraphRetriever:
    """Retrieve related documents and entities from the knowledge graph."""

    def __init__(self, graph: nx.DiGraph, session: Session | None = None):
        """Initialize the graph retriever.

        Args:
            graph: NetworkX directed graph
            session: Optional database session for page lookups
        """
        self.graph = graph
        self.session = session

    def get_related_documents(
        self, doc_id: str, hops: int = 2, max_results: int = 10
    ) -> list[str]:
        """Get related documents via graph traversal.

        Args:
            doc_id: Starting document page_id
            hops: Number of hops to traverse
            max_results: Maximum documents to return

        Returns:
            List of related page_ids
        """
        start_node = f"page:{doc_id}"

        if start_node not in self.graph:
            logger.debug(f"Document {doc_id} not in graph")
            return []

        related = set()
        current = {start_node}

        for _ in range(hops):
            neighbors = set()
            for node in current:
                # Get all neighbors (both directions)
                neighbors.update(self.graph.successors(node))
                neighbors.update(self.graph.predecessors(node))
            related.update(neighbors)
            current = neighbors

        # Filter to only page nodes
        page_ids = []
        for node in related:
            if node.startswith("page:") and node != start_node:
                page_ids.append(node.replace("page:", ""))

        # Sort by connection strength and limit
        return self._rank_by_connection(start_node, page_ids)[:max_results]

    def _rank_by_connection(self, source: str, page_ids: list[str]) -> list[str]:
        """Rank pages by connection strength to source."""
        scored = []

        for page_id in page_ids:
            page_node = f"page:{page_id}"
            # Find common entities
            source_entities = set(self.graph.successors(source))
            page_entities = set(self.graph.successors(page_node))
            common = source_entities & page_entities

            # Score by number of common entities and edge weights
            score = len(common)
            for entity in common:
                # Add weight from both edges if present
                if self.graph.has_edge(source, entity):
                    score += self.graph[source][entity].get("weight", 1.0)
                if self.graph.has_edge(page_node, entity):
                    score += self.graph[page_node][entity].get("weight", 1.0)

            scored.append((page_id, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [page_id for page_id, _ in scored]

    def find_by_entity(self, entity_name: str, entity_type: str | None = None) -> list[str]:
        """Find all documents mentioning an entity.

        Args:
            entity_name: Name of the entity to search for
            entity_type: Optional entity type filter

        Returns:
            List of page_ids
        """
        # Find matching entity node
        entity_id = self._find_entity_node(entity_name, entity_type)

        if not entity_id:
            logger.debug(f"Entity '{entity_name}' not found in graph")
            return []

        # Get all pages pointing to this entity
        predecessors = list(self.graph.predecessors(entity_id))
        page_ids = []

        for node in predecessors:
            if node.startswith("page:"):
                page_ids.append(node.replace("page:", ""))

        return page_ids

    def _find_entity_node(self, name: str, entity_type: str | None = None) -> str | None:
        """Find entity node by name (case-insensitive) and optional type."""
        name_lower = name.lower()

        for node_id, data in self.graph.nodes(data=True):
            if node_id.startswith("page:"):
                continue

            # Check type filter
            if entity_type and data.get("node_type") != entity_type:
                continue

            # Check name match
            node_name = data.get("name", "").lower()
            if node_name == name_lower:
                return node_id

            # Check aliases
            aliases = data.get("aliases", [])
            for alias in aliases:
                if alias.lower() == name_lower:
                    return node_id

        return None

    def get_entity_documents(self, entity_id: str) -> list[dict]:
        """Get all documents for an entity with details.

        Args:
            entity_id: Entity ID in the graph

        Returns:
            List of dicts with page details
        """
        if entity_id not in self.graph:
            return []

        results = []
        for predecessor in self.graph.predecessors(entity_id):
            if predecessor.startswith("page:"):
                page_id = predecessor.replace("page:", "")
                edge_data = self.graph[predecessor][entity_id]

                result = {
                    "page_id": page_id,
                    "relation_type": edge_data.get("relation_type", "mentions"),
                    "weight": edge_data.get("weight", 1.0),
                }

                # Get page details if session available
                if self.session:
                    page = self.session.execute(
                        select(RawPage).where(RawPage.page_id == page_id)
                    ).scalar_one_or_none()
                    if page:
                        result["title"] = page.title
                        result["url"] = page.url
                        result["space_key"] = page.space_key

                results.append(result)

        # Sort by weight
        results.sort(key=lambda x: x["weight"], reverse=True)
        return results

    def get_document_entities(self, page_id: str) -> list[dict]:
        """Get all entities for a document.

        Args:
            page_id: Document page ID

        Returns:
            List of dicts with entity details
        """
        node_id = f"page:{page_id}"
        if node_id not in self.graph:
            return []

        results = []
        for successor in self.graph.successors(node_id):
            if not successor.startswith("page:"):
                edge_data = self.graph[node_id][successor]
                node_data = self.graph.nodes[successor]

                results.append({
                    "entity_id": successor,
                    "name": node_data.get("name", successor),
                    "entity_type": node_data.get("node_type", "unknown"),
                    "relation_type": edge_data.get("relation_type", "mentions"),
                    "weight": edge_data.get("weight", 1.0),
                })

        return results

    def get_common_entities(self, page_ids: list[str]) -> list[dict]:
        """Find entities common to multiple documents.

        Useful for understanding what topics connect a set of search results.

        Args:
            page_ids: List of document page IDs

        Returns:
            List of common entities with occurrence count
        """
        if not page_ids:
            return []

        entity_counts: dict[str, dict] = {}

        for page_id in page_ids:
            node_id = f"page:{page_id}"
            if node_id not in self.graph:
                continue

            for successor in self.graph.successors(node_id):
                if successor.startswith("page:"):
                    continue

                if successor not in entity_counts:
                    node_data = self.graph.nodes[successor]
                    entity_counts[successor] = {
                        "entity_id": successor,
                        "name": node_data.get("name", successor),
                        "entity_type": node_data.get("node_type", "unknown"),
                        "count": 0,
                        "total_weight": 0.0,
                    }

                entity_counts[successor]["count"] += 1
                edge_data = self.graph[node_id][successor]
                entity_counts[successor]["total_weight"] += edge_data.get("weight", 1.0)

        # Filter to entities appearing in multiple docs
        common = [e for e in entity_counts.values() if e["count"] > 1]
        common.sort(key=lambda x: (x["count"], x["total_weight"]), reverse=True)

        return common

    def expand_query_with_entities(
        self, query: str, page_ids: list[str], top_k: int = 3
    ) -> list[str]:
        """Expand search by finding additional docs through common entities.

        Args:
            query: Original search query
            page_ids: Page IDs from initial search
            top_k: Number of additional pages to return

        Returns:
            Additional page_ids to include in results
        """
        if not page_ids:
            return []

        # Find common entities
        common_entities = self.get_common_entities(page_ids)

        if not common_entities:
            return []

        # Get pages from top entities
        additional_pages = set()
        for entity in common_entities[:5]:  # Top 5 entities
            entity_pages = self.find_by_entity(
                entity["name"], entity["entity_type"]
            )
            additional_pages.update(entity_pages)

        # Remove already-found pages
        additional_pages -= set(page_ids)

        # Score by how many common entities they share
        scored = []
        for page_id in additional_pages:
            page_entities = self.get_document_entities(page_id)
            page_entity_ids = {e["entity_id"] for e in page_entities}
            common_entity_ids = {e["entity_id"] for e in common_entities}
            overlap = len(page_entity_ids & common_entity_ids)
            if overlap > 0:
                scored.append((page_id, overlap))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [page_id for page_id, _ in scored[:top_k]]
