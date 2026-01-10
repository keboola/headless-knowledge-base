# Phase 06: Search API - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 05 and 05.5 are complete

## Implementation Tasks

### 1. API Schemas
- [ ] Create/update `api/schemas.py`
- [ ] Define SearchRequest model
- [ ] Define SearchResult model
- [ ] Define SearchResponse model

### 2. Retriever
- [ ] Create `vectorstore/retriever.py`
- [ ] Implement `search()` method
- [ ] Add filter application
- [ ] Add result enrichment
- [ ] Add timing measurement

### 3. Search Endpoint
- [ ] Create `api/search.py`
- [ ] Implement POST `/api/v1/search`
- [ ] Wire up retriever
- [ ] Add request validation
- [ ] Add error handling

### 4. Metadata Filters
- [ ] Implement space_key filter
- [ ] Implement doc_type filter
- [ ] Implement topics filter (any match)
- [ ] Implement date filters

### 5. Response Enrichment
- [ ] Add Confluence URLs to results
- [ ] Include full metadata
- [ ] Add pagination info

### 6. Testing
- [ ] Test basic search
- [ ] Test with filters
- [ ] Test different search methods
- [ ] Measure performance

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-06): search API"
