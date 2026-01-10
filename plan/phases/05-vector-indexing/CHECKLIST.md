# Phase 05: Vector Indexing - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 04 is complete
- [ ] Pull embedding model: `ollama pull mxbai-embed-large`
- [ ] Verify ChromaDB is accessible

## Implementation Tasks

### 1. Embeddings Interface
- [ ] Create `vectorstore/__init__.py`
- [ ] Create `vectorstore/embeddings.py`
- [ ] Define BaseEmbeddings abstract class
- [ ] Implement OllamaEmbeddings
- [ ] Test embedding generation

### 2. ChromaDB Client
- [ ] Create `vectorstore/client.py`
- [ ] Initialize HTTP client
- [ ] Create/get collection
- [ ] Implement `upsert()` method
- [ ] Implement `delete()` method
- [ ] Implement `count()` method

### 3. Indexer
- [ ] Create `vectorstore/indexer.py`
- [ ] Implement batch processing
- [ ] Build metadata from chunks
- [ ] Handle embedding errors
- [ ] Add progress tracking

### 4. Metadata Mapping
- [ ] Map chunk fields to ChromaDB metadata
- [ ] Serialize JSON fields (topics, etc.)
- [ ] Handle optional fields

### 5. Deletion Handling
- [ ] Track indexed chunk IDs
- [ ] Delete removed chunks from index
- [ ] Handle orphaned embeddings

### 6. CLI Command
- [ ] Add `index` command to CLI
- [ ] Add `--space` filter
- [ ] Add `--reindex` flag
- [ ] Add `--batch-size` option
- [ ] Add progress bar

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-05): vector indexing"
