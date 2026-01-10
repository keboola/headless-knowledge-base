# Phase 04.5: Knowledge Graph

## Overview

Automatically build a knowledge graph connecting documents, people, topics, and entities for multi-hop reasoning.

## Dependencies

- **Requires**: Phase 03 (Content Parsing), Phase 04 (Metadata)
- **Blocks**: None (enhancement)
- **Parallel**: Can run alongside Phase 05

## Deliverables

```
src/knowledge_base/
├── graph/
│   ├── __init__.py
│   ├── entity_extractor.py   # LLM entity extraction
│   ├── graph_builder.py      # NetworkX graph construction
│   ├── graph_retriever.py    # Query graph for context
│   └── models.py             # Entity models
└── db/models.py              # Add Entity, Relationship tables
```

## Technical Specification

### Entity Types

| Type | Examples | Extraction Method |
|------|----------|-------------------|
| Person | "John Smith", "Mary" | NER + LLM |
| Team | "Engineering", "Sales" | LLM classification |
| Product | "Snowflake", "GCP" | LLM + keyword list |
| Location | "Prague office", "US" | NER |
| Topic | "onboarding", "security" | From metadata |

### Database Models

```python
class Entity(Base):
    __tablename__ = "entities"

    id: int
    entity_id: str            # Canonical ID
    name: str                 # Display name
    entity_type: str          # person, team, product, location, topic
    aliases: str              # JSON: alternative names
    created_at: datetime

class Relationship(Base):
    __tablename__ = "relationships"

    id: int
    source_id: str            # Entity or chunk ID
    target_id: str            # Entity ID
    relation_type: str        # "mentions", "authored_by", "belongs_to"
    weight: float             # Relationship strength
    created_at: datetime
```

### Auto Graph Builder

```python
class AutoGraphBuilder:
    def __init__(self, llm: BaseLLM):
        self.llm = llm
        self.graph = nx.DiGraph()

    async def process_document(self, doc: Document):
        # 1. Extract entities using LLM
        entities = await self.extract_entities(doc.content)

        # 2. Resolve to canonical forms
        resolved = await self.resolve_entities(entities)

        # 3. Create graph edges
        for entity_type, entity_list in resolved.items():
            for entity in entity_list:
                self.add_relationship(
                    doc.page_id, entity,
                    relation=f"mentions_{entity_type}"
                )

        # 4. Link author
        self.add_relationship(doc.page_id, doc.author, "authored_by")

        # 5. Link to space
        self.add_relationship(doc.page_id, doc.space_key, "belongs_to")
```

### Entity Extraction Prompt

```
Extract entities from this document.

Content: {content}

Extract as JSON:
{
    "people": ["full names mentioned"],
    "teams": ["team or department names"],
    "products": ["products, services, tools"],
    "locations": ["offices, cities, regions"]
}

Only include clearly mentioned entities, not inferred ones.
```

### Graph Retriever

```python
class GraphRetriever:
    def get_related_context(self, doc_id: str, hops: int = 2) -> list[str]:
        """Get related documents via graph traversal."""
        related = set()
        current = {doc_id}

        for _ in range(hops):
            neighbors = set()
            for node in current:
                neighbors.update(self.graph.neighbors(node))
            related.update(neighbors)
            current = neighbors

        return [n for n in related if n.startswith("page_")]

    def find_by_entity(self, entity: str) -> list[str]:
        """Find all documents mentioning an entity."""
        if entity not in self.graph:
            return []
        return list(self.graph.predecessors(entity))
```

### CLI Command

```bash
# Build graph from existing documents
python -m knowledge_base.cli graph build

# Query graph
python -m knowledge_base.cli graph query --entity="John Smith"

# Export graph for visualization
python -m knowledge_base.cli graph export --format=graphml
```

## Definition of Done

- [ ] Entities extracted from all documents
- [ ] Graph built with relationships
- [ ] Entity resolution working (aliases mapped)
- [ ] Graph queries return related documents
- [ ] Graph persisted to SQLite
