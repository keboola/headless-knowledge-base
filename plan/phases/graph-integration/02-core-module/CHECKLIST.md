# Phase 2: Core Graph Module - Checklist

## Core Implementation
- [x] Create `src/knowledge_base/graph/entity_schemas.py` and define models.
- [x] Create `src/knowledge_base/graph/graphiti_client.py` factory function.
- [x] Create `src/knowledge_base/graph/graphiti_builder.py` class.
    - [x] Implement `build_graph_from_documents` (via process_document/process_chunk).
    - [x] Implement `add_episode` logic.
- [x] Create `src/knowledge_base/graph/graphiti_retriever.py` class.
    - [x] Implement `search` method.
    - [x] Implement `get_context` methods (get_related_documents, find_by_entity, etc.).

## Chunk Linking
- [x] Update builder to accept chunk metadata (chunk_id, chunk_index).
- [x] Verify edges are created between chunks and extracted entities (via Graphiti episodes).

## Testing
- [x] Write unit tests for `graphiti_client.py` (in tests/test_graphiti.py).
- [x] Write unit tests for `entity_schemas.py` (in tests/test_graphiti.py).
- [ ] Write integration test for ingestion (Builder) -> retrieval (Retriever) loop. (requires live Graphiti)
