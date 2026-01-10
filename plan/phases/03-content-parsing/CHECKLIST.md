# Phase 03: Content Parsing - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 02 is complete
- [ ] Review sample Confluence HTML structure

## Implementation Tasks

### 1. Database Model
- [ ] Add Chunk model to `db/models.py`
- [ ] Run migrations / create table
- [ ] Test chunk storage

### 2. HTML Chunker
- [ ] Create `chunking/__init__.py`
- [ ] Create `chunking/html_chunker.py`
- [ ] Implement HTML parsing with BeautifulSoup
- [ ] Implement text extraction
- [ ] Implement header hierarchy tracking
- [ ] Implement size-based splitting with overlap

### 3. Macro Handler
- [ ] Create `chunking/macro_handler.py`
- [ ] Handle `{code}` blocks
- [ ] Handle `{info}`, `{warning}`, `{note}` panels
- [ ] Handle `{expand}` sections
- [ ] Handle `{panel}` sections
- [ ] Skip `{toc}` and `{children}`

### 4. Table Handler
- [ ] Create `chunking/table_handler.py`
- [ ] Convert tables to markdown format
- [ ] Implement small table handling (keep intact)
- [ ] Implement large table handling (row-by-row)
- [ ] Preserve column headers in each chunk

### 5. Chunking Strategies
- [ ] Create `chunking/strategies.py`
- [ ] Implement section-based chunking
- [ ] Implement semantic chunking (optional)
- [ ] Implement code-aware chunking
- [ ] Add chunk overlap logic

### 6. Attachment Parsing (Optional)
- [ ] Create `attachments/pdf.py` with pypdf
- [ ] Create `attachments/docx.py` with python-docx
- [ ] Link attachment chunks to parent page

### 7. CLI Command
- [ ] Add `parse` command to CLI
- [ ] Add `--space` filter option
- [ ] Add `--verbose` flag
- [ ] Add progress bar

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-03): content parsing"
