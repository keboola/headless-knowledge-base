# ADR-0012: Search Quality, Fuzzy Entity Resolution, and Community Detection

## Status
Accepted

## Date
2026-04-06

## Context

Users reported 5 critical KB search quality issues:
1. **All scores identical (1.100)** — `graphiti.search()` returns `list[EntityEdge]` with no score field; retriever fell back to hardcoded 1.0, quality boost made everything 1.1.
2. **ask_question timeout** — query expansion (3x parallel searches) + LLM generation exceeded MCP timeout.
3. **Fragments not answers** — edge-only search missed episode content (chunk text BM25).
4. **Trivial key facts** — extraction prompt lacked guidance, producing "Keboola PRODUCT is a product of KEBOOLA".
5. **No score differentiation** — deduplication in `_deduplicate_results` was meaningless when all scores = 1.1.

Additionally, the knowledge graph had duplicate entities from slightly different LLM extractions (e.g., "Platform Team" vs "platform-team") and no topic community structure.

## Decision

### Search Quality (always active)
- Switch from `graphiti.search()` to `graphiti.search_()` with `COMBINED_HYBRID_SEARCH_RRF` config for real Reciprocal Rank Fusion scores on edges and episodes.
- Replace 3x parallel `search_with_expansion()` in `ask_question` MCP tool with single `search_knowledge()` call + `asyncio.wait_for()` timeout (45s) with fallback to returning raw search results.
- Improve batch extraction prompt with BAD/GOOD examples to reject circular/trivial facts (forward-only, affects future imports).

### Fuzzy Entity Resolution (opt-in: `BATCH_ENTITY_FUZZY_MERGE_ENABLED`)
- Embedding-based cosine similarity merge during batch import resolve phase.
- Union-find single-linkage clustering within same `entity_type`.
- Threshold configurable via `BATCH_ENTITY_SIMILARITY_THRESHOLD` (default 0.85).
- Standalone `fuzzy-merge` CLI command with `--dry-run` mode for existing graphs.
- CLI processes one entity_type at a time to avoid OOM; skips types exceeding `BATCH_FUZZY_MERGE_BATCH_SIZE` (default 500).

### Community Detection (opt-in: `COMMUNITY_DETECTION_ENABLED`)
- Pipeline Phase 6 calling Graphiti's built-in `build_communities()` (label propagation + LLM summarization).
- HNSW vector index on `Community.name_embedding` for fast similarity search.
- `search_communities` MCP tool and `build-communities` CLI command.

## Rationale

**search_() over search():** Graphiti's `search_()` returns `SearchResults` with parallel `edge_reranker_scores` / `episode_reranker_scores` lists. The older `search()` returns bare `EntityEdge` objects with no score attribute. RRF fusion of BM25 + cosine similarity across edges and episodes gives meaningful ranking.

**Single search over query expansion:** Three parallel searches tripled latency and produced mostly-duplicate results that couldn't be differentiated (identical scores). A single search with RRF is faster and produces better-ranked results.

**Fuzzy merge as opt-in:** Embedding-based merge adds a dependency on the embedding provider at resolve time. The exact-match resolver handles 90%+ of duplicates (case, whitespace, punctuation). Fuzzy merge is a refinement, not a requirement.

**Community detection as opt-in:** `build_communities()` is expensive on large graphs (LLM call per community). Better to run explicitly after a batch import than on every pipeline execution.

## Consequences

**Positive:**
- Search results have varying scores reflecting actual relevance
- `ask_question` reliably responds within 60 seconds
- Episode content (chunk text) included in search results via BM25
- Cleaner entity graph when fuzzy merge is enabled
- Topic communities provide high-level knowledge structure

**Negative:**
- Fuzzy merge CLI is O(n^2) per entity type — infeasible for types with >500 entities without HNSW-based approach
- Community detection requires significant time/compute on large graphs (30+ min for 196K entities)
- Improved extraction prompt only benefits future imports, not existing data

**Operational:**
- New config flags: `MCP_ASK_QUESTION_SEARCH_LIMIT`, `MCP_ASK_QUESTION_LLM_TIMEOUT`, `BATCH_ENTITY_FUZZY_MERGE_ENABLED`, `BATCH_FUZZY_MERGE_BATCH_SIZE`, `COMMUNITY_DETECTION_ENABLED`, `COMMUNITY_MIN_CLUSTER_SIZE`, `COMMUNITY_SEARCH_LIMIT`
- New CLI commands: `fuzzy-merge`, `build-communities`
- New MCP tool: `search_communities`

## References

- PR #51: Implementation
- `src/knowledge_base/graph/graphiti_retriever.py` — search_() integration
- `src/knowledge_base/batch/resolver.py` — fuzzy merge logic
- `src/knowledge_base/batch/pipeline.py` — Phase 6 communities
- `src/knowledge_base/mcp/tools.py` — search_communities tool
- Graphiti search_config_recipes: `COMBINED_HYBRID_SEARCH_RRF`
