# Phase 4: Clean Cutover - Checklist

## Cleanup
- [ ] Remove `src/knowledge_base/graph/graph_builder.py`.
- [ ] Remove `src/knowledge_base/graph/graph_retriever.py`.
- [ ] Remove Entity/Relationship models from `db/models.py`.
- [ ] Create migration to drop old SQL tables (if applicable/needed).
- [ ] Remove `networkx` from `pyproject.toml` (if safe).

## Migration Script
- [ ] Implement `scripts/resync_to_graphiti.py`.
- [ ] Add CLI command `knowledge-base graph resync`.

## Execution
- [ ] Run `knowledge-base graph resync`.
- [ ] Verify graph size/node count matches expectation.

## Sanity Check
- [ ] Run full test suite `pytest`.
