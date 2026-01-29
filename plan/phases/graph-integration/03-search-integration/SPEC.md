# Phase 3: Search Integration - Specification

## Goal
Integrate the new Graphiti-based retrieval into the main hybrid search pipeline, making it available for RAG.

## Tasks

### 3.1 Modify `src/knowledge_base/search/hybrid.py`
- Inject `GraphRetriever` dependency.
- Add `use_graph_expansion` parameter to search methods.
- **Default**: `False` (Opt-in).

### 3.2 Result Merging
- Implement logic to merge graph traversal results with Vector + Keyword (RRF) results.
- Ensure graph results don't overwhelm precision (reranking might be needed later, but simple merging for now).

### 3.3 Future-Proofing (Stub)
- Prepare a placeholder for "Query Routing" logic (Phase 6) which will decide when to enable graph expansion automatically.

## Success Criteria
- Search API accepts `use_graph_expansion` flag.
- When enabled, results include graph-derived context.
- When disabled, behavior matches current baseline.
