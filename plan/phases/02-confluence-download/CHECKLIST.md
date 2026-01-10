# Phase 02: Confluence Download - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 01 is complete
- [ ] Obtain Confluence API token
- [ ] Add credentials to `.env`

## Implementation Tasks

### 1. Database Setup
- [ ] Create `src/knowledge_base/db/__init__.py`
- [ ] Create `src/knowledge_base/db/database.py` with SQLite connection
- [ ] Create `src/knowledge_base/db/models.py` with RawPage model
- [ ] Test database creation and table setup

### 2. Confluence Client
- [ ] Create `src/knowledge_base/confluence/__init__.py`
- [ ] Create `src/knowledge_base/confluence/models.py` with Page dataclass
- [ ] Create `src/knowledge_base/confluence/client.py`
- [ ] Implement authentication
- [ ] Implement `get_all_pages()` with pagination
- [ ] Implement `get_page_content()`
- [ ] Implement `get_page_permissions()`

### 3. Rate Limiting
- [ ] Add tenacity to dependencies
- [ ] Implement exponential backoff retry
- [ ] Handle 429 responses gracefully
- [ ] Add request throttling (5 req/sec)

### 4. Downloader
- [ ] Create `src/knowledge_base/confluence/downloader.py`
- [ ] Implement full space download
- [ ] Implement incremental sync (new/updated only)
- [ ] Handle deleted pages
- [ ] Add progress reporting

### 5. CLI Command
- [ ] Create `src/knowledge_base/cli.py`
- [ ] Add `download` command with Click
- [ ] Add `--spaces` argument
- [ ] Add `--verbose` flag
- [ ] Add `--resume` flag

### 6. Staleness Detection
- [ ] Add `is_potentially_stale` field to RawPage model
- [ ] Add `staleness_reason` field to RawPage model
- [ ] Implement `calculate_staleness()` function (2+ years = stale)
- [ ] Flag stale docs during download

### 7. Complete Extraction
- [ ] Extract labels/tags from pages
- [ ] Extract parent_id for hierarchy
- [ ] Extract attachments list
- [ ] Verify no data left behind

### 8. Governance Metadata
- [ ] Create `governance_metadata` table
- [ ] Implement `extract_governance_from_labels()`
- [ ] Extract: owner, reviewed_by, reviewed_at, classification, doc_type
- [ ] Default classification to "internal" if not specified

### 9. Rebase Command
- [ ] Add `sync --rebase` CLI command
- [ ] Implement `rebase_from_confluence()` function
- [ ] Preserve enrichments on rebase

### 10. Testing
- [ ] Test with single page
- [ ] Test with full space
- [ ] Test rate limiting
- [ ] Test resume after interruption
- [ ] Test Celery task execution

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-02): confluence download"
