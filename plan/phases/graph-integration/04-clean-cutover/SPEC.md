# Phase 4: Clean Cutover - Specification

## Goal
Remove technical debt by deleting the old NetworkX/SQLAlchemy graph implementation and establishing Graphiti as the sole graph source of truth.

## Tasks

### 4.1 Delete Old Code
Remove files and dependencies related to the legacy graph implementation:
- `src/knowledge_base/graph/graph_builder.py`
- `src/knowledge_base/graph/graph_retriever.py`
- `src/knowledge_base/db/models.py` (Entity/Relationship tables only)
- `networkx` dependency (if not used by Graphiti internally).

### 4.2 Full Re-Sync Tool
Create `scripts/resync_to_graphiti.py`:
- Iterate through all Source of Truth documents (ChromaDB/Confluence).
- Feed them into `GraphitiBuilder`.
- Rebuild the graph from scratch.

### 4.3 Database Configuration Finalization
- Ensure Kuzu/Neo4j settings are permanent in `config.py`.

## Success Criteria
- Old code is gone.
- Application builds and runs without `ImportError`.
- `resync_to_graphiti.py` completes successfully on the full dataset.
