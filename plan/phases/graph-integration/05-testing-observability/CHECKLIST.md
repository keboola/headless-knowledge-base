# Phase 5: Testing & Observability - Checklist

## Testing
- [x] Implement `tests/test_graphiti.py` (Unit) - 31 tests added.
- [ ] Implement `tests/integration/test_graphiti_integration.py` (Integration) - requires live Graphiti.
- [ ] Add E2E scenario in `tests/e2e/test_graph_full_flow.py` - requires ChromaDB + Graphiti.

## Observability
- [ ] Add timing decorators or middleware for graph queries. (future enhancement)
- [ ] Log extraction token counts and model used. (future enhancement)
- [x] Add "graph_hit" flag to search result metadata for tracking.

## Documentation
- [ ] Update `docs/ARCHITECTURE.md` to reflect the Graphiti/Kuzu/Neo4j stack.
- [x] Update `PROGRESS.md` to mark all graph integration phases as complete.
