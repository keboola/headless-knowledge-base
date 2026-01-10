# Phase 04.5: Knowledge Graph - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 03 and 04 are complete
- [ ] Add networkx to dependencies

## Implementation Tasks

### 1. Database Models
- [ ] Add Entity model to `db/models.py`
- [ ] Add Relationship model to `db/models.py`
- [ ] Run migrations / create tables

### 2. Entity Extractor
- [ ] Create `graph/__init__.py`
- [ ] Create `graph/models.py` with entity dataclasses
- [ ] Create `graph/entity_extractor.py`
- [ ] Define ENTITY_EXTRACTION_PROMPT
- [ ] Implement LLM-based extraction
- [ ] Add fallback NER (optional)

### 3. Entity Resolution
- [ ] Create canonical entity mappings
- [ ] Implement alias detection
- [ ] Handle name variations (John, John Smith, J. Smith)
- [ ] Map common product abbreviations

### 4. Graph Builder
- [ ] Create `graph/graph_builder.py`
- [ ] Initialize NetworkX DiGraph
- [ ] Implement `process_document()`
- [ ] Add relationship creation
- [ ] Implement graph persistence to SQLite

### 5. Graph Retriever
- [ ] Create `graph/graph_retriever.py`
- [ ] Implement `get_related_context()`
- [ ] Implement `find_by_entity()`
- [ ] Add multi-hop traversal

### 6. CLI Commands
- [ ] Add `graph build` command
- [ ] Add `graph query` command
- [ ] Add `graph export` command

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-04.5): knowledge graph"
