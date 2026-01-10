# Phase 04.5: Knowledge Graph - Test Plan

## Quick Verification

```bash
# Build graph
python -m knowledge_base.cli graph build --verbose

# Check entity count
sqlite3 knowledge_base.db "SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type;"

# Check relationship count
sqlite3 knowledge_base.db "SELECT relation_type, COUNT(*) FROM relationships GROUP BY relation_type;"
```

## Functional Tests

### 1. Entity Extraction
```bash
# Check extracted entities
sqlite3 knowledge_base.db "
SELECT name, entity_type, aliases
FROM entities
ORDER BY entity_type, name
LIMIT 20;
"
# Expected: Mix of people, products, teams
```

### 2. Graph Structure
```bash
# Check graph connectivity
python -c "
from knowledge_base.graph.graph_builder import GraphBuilder
builder = GraphBuilder()
builder.load_from_db()
print(f'Nodes: {builder.graph.number_of_nodes()}')
print(f'Edges: {builder.graph.number_of_edges()}')
"
```

### 3. Multi-hop Query
```bash
# Test related document retrieval
python -c "
from knowledge_base.graph.graph_retriever import GraphRetriever
retriever = GraphRetriever()
related = retriever.get_related_context('page_123', hops=2)
print(f'Found {len(related)} related documents')
for doc in related[:5]:
    print(f'  - {doc}')
"
```

### 4. Entity Search
```bash
# Find docs by entity
python -c "
from knowledge_base.graph.graph_retriever import GraphRetriever
retriever = GraphRetriever()
docs = retriever.find_by_entity('Snowflake')
print(f'Documents mentioning Snowflake: {len(docs)}')
"
```

### 5. Graph Export
```bash
# Export and verify
python -m knowledge_base.cli graph export --format=graphml -o graph.graphml
ls -la graph.graphml
# Expected: Non-empty file
```

## Unit Tests

```python
# tests/test_graph.py
import pytest
from knowledge_base.graph.entity_extractor import EntityExtractor
from knowledge_base.graph.graph_builder import GraphBuilder

@pytest.mark.asyncio
async def test_extract_entities():
    extractor = EntityExtractor()
    content = "John Smith from Engineering uses Snowflake daily."
    entities = await extractor.extract(content)

    assert "John Smith" in entities.get("people", [])
    assert "Engineering" in entities.get("teams", [])
    assert "Snowflake" in entities.get("products", [])

def test_graph_relationships():
    builder = GraphBuilder()
    builder.add_relationship("page_1", "John Smith", "authored_by")
    builder.add_relationship("page_1", "Snowflake", "mentions_product")

    assert builder.graph.has_edge("page_1", "John Smith")
    assert builder.graph.has_edge("page_1", "Snowflake")

def test_multi_hop_retrieval():
    builder = GraphBuilder()
    builder.add_relationship("page_1", "topic_A", "mentions_topic")
    builder.add_relationship("page_2", "topic_A", "mentions_topic")

    retriever = GraphRetriever(builder.graph)
    related = retriever.get_related_context("page_1", hops=2)

    assert "page_2" in related
```

## Success Criteria

- [ ] Entities extracted from all documents
- [ ] Graph has reasonable node/edge ratio
- [ ] Multi-hop queries return relevant docs
- [ ] Entity aliases resolved correctly
- [ ] Graph persists across restarts
