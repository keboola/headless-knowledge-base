# Phase 0: Baseline & Spike - Specification

## Goal
Establish a performance baseline for the current retrieval system and validate the feasibility of the Graphiti + Kuzu stack before full implementation.

## Tasks

### 0.1 Baseline Current Retrieval Quality
Create a quantitative baseline to measure improvements against.
- **Test Set**: 20-30 queries covering:
    - Simple factual queries (should NOT need graph).
    - Multi-hop queries (e.g., "What policies apply to the engineering team's contractors?").
    - Entity-specific queries (e.g., "What documents mention John Smith?").
- **Metrics**:
    - Recall@5, Recall@10.
    - Precision (relevance).
    - Latency (p50, p95).

### 0.2 Spike: Test Graphiti on 100 Documents
Validate the new stack in a sandbox environment.
- **Scope**: 100 sample documents.
- **Objectives**:
    1.  Verify Graphiti + Kuzu integration (Kuzu v0.4.x).
    2.  Assess extraction quality vs. current `EntityExtractor`.
    3.  Measure extraction latency and LLM token usage.
    4.  Measure query latency with graph traversal.

### 0.3 Compare Extraction Quality
Direct comparison of entity extractors on 50 documents.
- **Contenders**:
    - Current `EntityExtractor` (Claude Haiku).
    - Graphiti's built-in extraction.
- **Comparison Points**:
    - Entity types detected.
    - Alias/disambiguation quality.
    - LLM cost per document.

## Success Criteria
- [ ] Baseline metrics recorded.
- [ ] Graphiti + Kuzu integration proven working.
- [ ] Extraction quality is comparable or better than current solution.
- [ ] Graph query latency < 500ms (p95).
