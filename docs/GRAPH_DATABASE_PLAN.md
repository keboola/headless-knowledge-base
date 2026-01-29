# Graph Database Integration Plan for Headless Knowledge Base

## Executive Summary

After researching both **Cognee** and **Graphiti**, I recommend **Graphiti** for integrating a proper graph database layer into the headless knowledge base.

**Key Decisions:**
- **Framework**: Graphiti (not Cognee)
- **Dev Database**: Kuzu (embedded, zero setup)
- **Prod Database**: Neo4j (configurable via env vars)
- **Migration**: Clean replacement (re-ingest from source, delete old code)
- **Graph Expansion**: Opt-in per query (not default)

> **Note**: Cognee and Graphiti are frameworks/libraries, not databases. They provide the API for building knowledge graphs, while the actual storage is handled by graph databases like Kuzu or Neo4j underneath.

---

## Expert Review Feedback (Incorporated)

| Concern | How Addressed |
|---------|---------------|
| Missing baseline metrics | Added Phase 0: Baseline & Spike |
| LLM extraction cost unknown | Phase 0 compares extraction quality and cost |
| No rollback strategy | Clean cutover - re-ingest if issues; no dual-write complexity |
| Kuzu maturity concern | Phase 0 spike validates Graphiti+Kuzu integration |
| Keep EntityResolver | Preserved as post-processing layer |
| Graph expansion may hurt precision | Changed default to OFF (opt-in) |
| Missing chunk-level linking | Added chunk→entity edges requirement |
| Temporal queries need use cases | Added concrete use case section |
| Missing observability | Added metrics requirements in Phase 5 |

---

## Problem Statement (Why This Investment?)

Before adding graph complexity, we must quantify what we're fixing:

**Current Retrieval Gaps (to be measured in Phase 0):**
- Multi-hop queries that fail (e.g., "Who owns the onboarding process for the data team?")
- Entity disambiguation failures (e.g., "John" matching wrong person)
- Related document discovery limitations

**Success Criteria:**
- Improve multi-hop query recall from baseline to target (measure in Phase 0)
- Reduce entity disambiguation errors by X%
- Graph expansion improves relevance for complex queries without hurting simple queries

## Research Summary

### Graphiti (Recommended)
- **Focus**: Temporal-aware knowledge graphs for AI agents
- **Key Features**: Bi-temporal model, incremental updates, hybrid retrieval (semantic + BM25 + graph)
- **Backends**: Neo4j, FalkorDB, Kuzu (embedded), Amazon Neptune
- **GitHub**: 22.3k stars, active development
- **Best for**: Real-time knowledge graph updates with temporal tracking

### Cognee
- **Focus**: Full AI memory platform with ECL pipelines
- **Key Features**: Multi-layer semantic graphs, customizable ontologies, better multi-hop reasoning benchmarks
- **Backends**: Neo4j, various vector stores
- **GitHub**: 11.3k stars, active development
- **Best for**: Comprehensive AI memory with more control over graph structure

### Why Graphiti Wins

| Factor | Graphiti | Cognee |
|--------|----------|--------|
| **Temporal tracking** | Native bi-temporal model | Requires Graphiti integration |
| **Incremental updates** | Built-in, no recomputation | Full pipeline runs |
| **Scope** | Focused graph library | Full platform (overkill) |
| **ChromaDB coexistence** | Clean separation | May duplicate vector functionality |
| **Development mode** | Kuzu embedded (zero infra) | Requires external DB |
| **Learning curve** | Lower | Higher |

### Temporal Query Use Cases

The expert review asked: "What queries need 'as of date X' semantics?"

**Concrete use cases for bi-temporal model:**

1. **Document lifecycle tracking**
   - "What was the vacation policy before the January update?"
   - "Show me the onboarding doc as it existed when John joined"

2. **Entity relationship history**
   - "Who was the engineering lead before Sarah?"
   - "Which team owned this product last quarter?"

3. **Knowledge freshness**
   - "When was this information last verified?"
   - Filter out entities from deprecated/archived documents

4. **Audit trail**
   - "What did we know about X at the time of decision Y?"

**If these use cases don't apply**, temporal tracking is still useful for:
- Invalidating stale entity relationships automatically
- Prioritizing recently-updated knowledge in search results

---

## Current Architecture

```
ChromaDB (vectors) ← Source of truth for chunks
NetworkX (in-memory) ← Ephemeral graph, lost on restart
SQLAlchemy (Entity/Relationship) ← Graph persistence layer
BM25 + Vector hybrid search ← Primary retrieval
```

**Key Files:**
- `src/knowledge_base/graph/graph_builder.py` - NetworkX graph construction
- `src/knowledge_base/graph/graph_retriever.py` - Multi-hop traversal
- `src/knowledge_base/graph/entity_extractor.py` - LLM entity extraction
- `src/knowledge_base/db/models.py` - Entity, Relationship models
- `src/knowledge_base/search/hybrid.py` - BM25 + vector fusion

---

## Target Architecture

```
ChromaDB (vectors) ← Keep as source of truth for chunks
Graphiti + Neo4j/Kuzu ← Persistent temporal graph
Enhanced hybrid search ← BM25 + vector + graph traversal
```

---

## Implementation Plan

### Phase 0: Baseline & Spike (MUST DO FIRST)

**0.1 Baseline Current Retrieval Quality**
Create a test set of 20-30 queries covering:
- Simple factual queries (should NOT need graph)
- Multi-hop queries (e.g., "What policies apply to the engineering team's contractors?")
- Entity-specific queries (e.g., "What documents mention John Smith?")

Measure:
- Recall@5, Recall@10
- Precision (relevance of returned results)
- Latency (p50, p95)

**0.2 Spike: Test Graphiti on 100 Documents**
Before full commitment, validate:
1. Graphiti+Kuzu integration works (Kuzu is v0.4.x, relatively new)
2. Graphiti's entity extraction quality vs. your current `EntityExtractor`
3. Extraction latency and LLM token usage
4. Query latency with graph traversal

**0.3 Compare Extraction Quality**
Run both extractors on 50 sample documents:
- Your current `EntityExtractor` (Claude Haiku)
- Graphiti's built-in extraction

Compare:
- Entity types detected (Graphiti may extract different types)
- Alias/disambiguation quality
- LLM cost per document

**Exit Criteria for Phase 0:**
- [ ] Baseline metrics documented
- [ ] Graphiti+Kuzu spike working
- [ ] Extraction quality comparable or better
- [ ] No showstopper latency issues (graph query < 500ms p95)

---

### Phase 1: Infrastructure Setup

**1.1 Add Dependencies**
```toml
# pyproject.toml
"graphiti-core[anthropic,kuzu]>=0.26.0"
"neo4j>=5.26.0"  # Optional, for production
```

**1.2 Local Development (Kuzu - no Docker needed)**
Kuzu is embedded - data stored in `data/kuzu_graph/` directory. No server required.

**1.3 Docker Compose (optional Neo4j for production-like testing)**
```yaml
neo4j:
  image: neo4j:5.26-community
  ports: ["7474:7474", "7687:7687"]
  environment:
    - NEO4J_AUTH=neo4j/password
  profiles: [neo4j]  # Only starts with: docker compose --profile neo4j up
```

**1.4 Configuration**
Add to `src/knowledge_base/config.py`:
- `GRAPH_BACKEND`: "kuzu" (default) | "neo4j"
- `GRAPH_KUZU_PATH`: "data/kuzu_graph"
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
- `GRAPHITI_GROUP_ID`: Multi-tenancy support

---

### Phase 2: Core Graph Module

**2.1 New: `src/knowledge_base/graph/graphiti_client.py`**
- Factory for creating Graphiti instances
- Backend selection (Kuzu vs Neo4j) based on config
- LLM client configuration (reuse Anthropic settings)

**2.2 New: `src/knowledge_base/graph/entity_schemas.py`**
- Pydantic models for domain entities: DocumentEntity, PersonEntity, TeamEntity, ProductEntity, TopicEntity
- Matches existing EntityType enum

**2.3 New: `src/knowledge_base/graph/graphiti_builder.py`**
- Wraps Graphiti client (replaces `graph_builder.py`)
- Use `graphiti.add_episode()` for document ingestion
- Add bi-temporal metadata (event_time = page.updated_at)
- **Keep existing `EntityResolver`** as post-processing layer (preserves domain-specific alias logic)

**2.4 New: `src/knowledge_base/graph/graphiti_retriever.py`**
- Wraps `graphiti.search()` for hybrid retrieval (replaces `graph_retriever.py`)
- Same interface as existing `GraphRetriever` for easy swap

**2.5 Add Chunk-Level Entity Linking**
Current architecture indexes at chunk level (ChromaDB), but plan focuses on page-level entities.
- Add `chunk_id → entity` edges (not just `page_id → entity`)
- Enables more precise retrieval: "Which specific section mentions X?"

---

### Phase 3: Search Integration

**Modify: `src/knowledge_base/search/hybrid.py`**
- Add `GraphRetriever` dependency injection
- **Default graph expansion to OFF** (opt-in, not opt-out)
- Merge graph results into RRF fusion pipeline

```python
async def search(self, query: str, use_graph_expansion: bool = False):  # OFF by default
    results = await self._fused_search(query, k)
    if use_graph_expansion and self.graph_retriever:
        graph_results = await self.graph_retriever.search(query)
        results = self._merge_graph_results(results, graph_results)
    return results
```

**Why OFF by default?**
- Simple factual queries don't benefit from graph expansion
- Graph expansion can hurt precision on straightforward lookups
- Measure impact before making it default

**Future: Query Routing (Phase 6+)**
Add a classifier to automatically enable graph expansion for complex queries:
- Multi-hop queries → enable graph
- Entity-specific queries → enable graph
- Simple factual queries → skip graph

---

### Phase 4: Clean Cutover

**4.1 Delete Old Graph Code**
- Remove `graph_builder.py` (NetworkX implementation)
- Remove `graph_retriever.py` (NetworkX queries)
- Remove `Entity` and `Relationship` models from `db/models.py`
- Remove NetworkX dependency from `pyproject.toml`
- Drop old graph tables from SQLite

**4.2 Full Re-Sync**
Run complete document re-ingestion:
```bash
python scripts/resync_to_graphiti.py --source confluence
```

This re-processes all documents through Graphiti. No data migration needed - graph is rebuilt from source.

**4.3 Database Backend Configuration**
```bash
# Kuzu (default for dev)
GRAPH_BACKEND=kuzu
GRAPH_KUZU_PATH=data/kuzu_graph

# Neo4j (production)
GRAPH_BACKEND=neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=secret
```

**Why Clean Cutover?**
- No dual-write complexity
- No feature flag overhead
- Source of truth is Confluence/ChromaDB - graph can always be rebuilt
- Simpler codebase to maintain

---

### Phase 5: Testing & Observability

**5.1 Unit Tests**
- Mock Graphiti client
- Test entity schema validation

**5.2 Integration Tests**
- Test with real Kuzu embedded database
- Test incremental update behavior

**5.3 E2E Tests**
- Verify graph persists across restarts
- Test Confluence sync with graph updates
- Compare: queries with/without graph expansion

**5.4 Observability**
Add metrics for:
- Graph query latency (p50, p95, p99)
- Graph expansion effectiveness (did it improve results?)
- Entity extraction latency and token usage
- Cache hit rates (if caching graph queries)

---

### Phase 6: Future Enhancements (Out of Scope)

These are noted for future consideration but NOT part of initial implementation:

| Enhancement | Description |
|-------------|-------------|
| Query routing | Classifier to auto-enable graph for complex queries |
| External KB linking | Wikidata/company wiki for entity disambiguation |
| Confidence thresholds | Filter low-confidence entity extractions |
| Incremental sync | Handle Confluence page updates vs. creates differently |

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/knowledge_base/graph/graphiti_client.py` | Graphiti client factory |
| `src/knowledge_base/graph/graphiti_builder.py` | Replaces graph_builder.py |
| `src/knowledge_base/graph/graphiti_retriever.py` | Replaces graph_retriever.py |
| `src/knowledge_base/graph/entity_schemas.py` | Pydantic entity models |
| `scripts/resync_to_graphiti.py` | Full re-sync script |
| `tests/integration/test_graphiti.py` | Integration tests |

## Files to Modify

| File | Changes |
|------|---------|
| `pyproject.toml` | Add graphiti-core, kuzu, neo4j; remove networkx |
| `docker-compose.yml` | Add Neo4j service (optional profile) |
| `src/knowledge_base/config.py` | Add GRAPH_* settings |
| `src/knowledge_base/graph/__init__.py` | Export new implementations |
| `src/knowledge_base/graph/entity_extractor.py` | Keep `EntityResolver` for post-processing |
| `src/knowledge_base/search/hybrid.py` | Add optional graph expansion (OFF by default) |

## Files to Delete

| File | Reason |
|------|--------|
| `src/knowledge_base/graph/graph_builder.py` | Replaced by graphiti_builder.py |
| `src/knowledge_base/graph/graph_retriever.py` | Replaced by graphiti_retriever.py |
| `src/knowledge_base/db/models.py` Entity/Relationship | Graphiti handles persistence |

---

## Verification

1. **Unit tests**: `pytest tests/test_graph.py -v`
2. **Integration tests**: `pytest tests/integration/test_graphiti.py -v`
3. **Manual verification**:
   - Sync a Confluence space
   - Query via Slack bot
   - Verify related documents are discovered via graph traversal
   - Check graph data persists after restart

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **Graphiti extraction quality worse** | Phase 0 spike compares quality; keep EntityResolver as post-processing |
| **Kuzu maturity issues** | Phase 0 spike validates Graphiti+Kuzu; fallback to Neo4j if needed |
| **Search latency regression** | Phase 0 baseline establishes acceptable thresholds |
| **LLM cost increase** | Phase 0 measures token usage; batch processing; may use Haiku |
| **Graph expansion hurts precision** | Default OFF; measure impact before enabling |
| **Graphiti API changes** | Pin version in pyproject.toml, monitor releases |
| **Re-sync takes long time** | Re-sync runs during off-hours; incremental updates after initial sync |

---

## Sources

- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Cognee GitHub](https://github.com/topoteretes/cognee)
- [Cognee AI Memory Tools Evaluation](https://www.cognee.ai/blog/deep-dives/ai-memory-tools-evaluation)
- [Cognee-Graphiti Integration](https://www.cognee.ai/blog/deep-dives/cognee-graphiti-integrating-temporal-aware-graphs)
