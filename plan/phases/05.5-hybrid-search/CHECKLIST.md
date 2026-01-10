# Phase 05.5: Hybrid Search - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 05 is complete
- [ ] Add rank-bm25 to dependencies

## Implementation Tasks

### 1. BM25 Index
- [ ] Create `search/__init__.py`
- [ ] Create `search/bm25.py`
- [ ] Implement tokenization
- [ ] Implement index building
- [ ] Implement search method
- [ ] Add index persistence (pickle)

### 2. Rank Fusion
- [ ] Create `search/fusion.py`
- [ ] Implement Reciprocal Rank Fusion
- [ ] Support configurable weights
- [ ] Handle empty result sets

### 3. Hybrid Retriever
- [ ] Create `search/hybrid.py`
- [ ] Combine BM25 and vector search
- [ ] Apply RRF to merge results
- [ ] Return unified result format

### 4. Index Persistence
- [ ] Save BM25 index to disk
- [ ] Load on startup
- [ ] Rebuild on content changes

### 5. CLI Commands
- [ ] Add `search rebuild-bm25` command
- [ ] Add `search query` command for testing
- [ ] Add `--verbose` flag to show both result sets

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-05.5): hybrid search"
