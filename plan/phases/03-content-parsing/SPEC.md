# Phase 03: Content Parsing

## Overview

Parse raw HTML from Confluence into clean, structured text chunks suitable for embedding.

## Dependencies

- **Requires**: Phase 02 (Confluence Download)
- **Blocks**: Phase 04 (Metadata), Phase 05 (Indexing)

## Deliverables

```
src/knowledge_base/
├── chunking/
│   ├── __init__.py
│   ├── html_chunker.py      # HTML → text conversion
│   ├── table_handler.py     # Table preservation
│   ├── macro_handler.py     # Confluence macro handling
│   └── strategies.py        # Chunking strategies
├── attachments/
│   ├── __init__.py
│   ├── pdf.py               # PDF text extraction
│   └── docx.py              # DOCX text extraction
└── db/models.py             # Add Chunk model
```

## Technical Specification

### Chunk Model

```python
class Chunk(Base):
    __tablename__ = "chunks"

    id: int
    chunk_id: str             # Unique chunk identifier
    page_id: str              # Parent page (FK to raw_pages)
    content: str              # Clean text content
    chunk_type: str           # "text", "code", "table", "list"
    chunk_index: int          # Order within page
    char_count: int           # Content length
    parent_headers: str       # JSON: hierarchy of headers above this chunk
    created_at: datetime
```

### Adaptive Chunking Strategy

| Document Type | Strategy | Max Chunk Size |
|--------------|----------|----------------|
| Policy docs | Section-based (by headers) | 1500 chars |
| How-to guides | Step-based (numbered lists) | 1000 chars |
| Meeting notes | Semantic (topic shifts) | 1000 chars |
| Tables | Keep intact | 2000 chars |
| Code blocks | Keep intact | 1500 chars |

### Confluence Macro Handling

| Macro | Strategy |
|-------|----------|
| `{code}` | Preserve as code block, set `chunk_type="code"` |
| `{info}`, `{warning}`, `{note}` | Extract content, add prefix |
| `{expand}` | Expand and include |
| `{panel}` | Extract inner content |
| `{toc}` | Skip (auto-generated) |
| `{children}` | Skip (navigational) |
| `{excerpt}` | Include as summary candidate |

### HTML Chunker

```python
class HTMLChunker:
    def __init__(self, max_chunk_size: int = 1000, overlap: int = 100):
        self.max_size = max_chunk_size
        self.overlap = overlap

    def chunk(self, html: str, page_id: str) -> list[Chunk]:
        """Convert HTML to chunks preserving structure."""
        # 1. Parse HTML with BeautifulSoup
        # 2. Handle Confluence macros
        # 3. Preserve tables and code blocks
        # 4. Split by headers/sections
        # 5. Apply size limits with overlap
```

### Table Handler

```python
class TableHandler:
    def process(self, table_element) -> list[Chunk]:
        """Convert table to chunks.

        Small tables (<20 rows): Keep as single markdown chunk
        Large tables: Row-by-row with header context
        """
```

### CLI Command

```bash
# Parse all downloaded pages
python -m knowledge_base.cli parse

# Parse specific space
python -m knowledge_base.cli parse --space=ENG

# Verbose with stats
python -m knowledge_base.cli parse --verbose
```

## Definition of Done

- [ ] All raw pages parsed into chunks
- [ ] Tables preserved as markdown
- [ ] Code blocks kept intact
- [ ] Confluence macros handled correctly
- [ ] Header hierarchy tracked
- [ ] Idempotent: re-run regenerates chunks
