# Phase 5: Testing & Observability - Specification

## Goal
Ensure the long-term reliability and performance of the graph integration through comprehensive testing and monitoring.

## Tasks

### 5.1 Unit & Integration Tests
- **Unit Tests**: Mock Graphiti client to test internal logic, schema validation, and edge cases.
- **Integration Tests**: Test with a real Kuzu embedded database to verify incremental update behavior and persistence.

### 5.2 E2E Tests
- Verify graph data persists across application restarts.
- Test the full Confluence sync pipeline with graph updates.
- Comparative search tests: Run the same query with and without graph expansion and assert on result quality/structure.

### 5.3 Observability & Metrics
Add instrumentation to track:
- **Graph Query Latency**: (p50, p95, p99) to detect performance regressions.
- **Expansion Effectiveness**: Track how often graph results are included in the final RAG context.
- **Extraction Costs**: Monitor LLM token usage and latency for entity extraction.
- **Cache Hit Rates**: Monitor efficiency of graph query results if caching is implemented.

## Success Criteria
- Test coverage for graph modules exceeds 80%.
- E2E tests pass consistently in CI.
- Performance metrics are visible in application logs/monitoring.
