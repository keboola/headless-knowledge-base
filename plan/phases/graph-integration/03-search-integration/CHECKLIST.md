# Phase 3: Search Integration - Checklist

## Search Engine
- [x] Import `GraphRetriever` in `hybrid.py` (or inject via factory).
- [x] Update `search()` signature to accept `use_graph_expansion: bool = None` (defaults to settings).
- [x] Implement `_merge_graph_results()` method.
- [x] Implement `_convert_graph_results()` method.
- [x] Implement `_apply_graph_expansion()` method.
- [x] Call `graph_retriever.search()` when flag is True.

## API/CLI
- [ ] Update CLI search command to support `--graph/--no-graph` flag. (optional, currently via config)
- [ ] Update API endpoint (if exists) to accept this parameter. (optional, currently via config)

## Testing
- [x] Unit test `hybrid.py` graph integration (in tests/test_graphiti.py).
- [x] Verify merging logic works as expected (tests pass).
