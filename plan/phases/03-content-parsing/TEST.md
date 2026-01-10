# Phase 03: Content Parsing - Test Plan

## Quick Verification

```bash
# Run parsing
python -m knowledge_base.cli parse --verbose

# Check chunk count
sqlite3 knowledge_base.db "SELECT COUNT(*) FROM chunks;"
# Expected: Multiple chunks per page

# Verify chunk content quality
sqlite3 knowledge_base.db "
SELECT chunk_type, COUNT(*), AVG(char_count)
FROM chunks
GROUP BY chunk_type;
"
```

## Functional Tests

### 1. Basic Parsing
```bash
# Parse and check structure
python -m knowledge_base.cli parse

sqlite3 knowledge_base.db "
SELECT c.chunk_id, c.chunk_type, SUBSTR(c.content, 1, 100)
FROM chunks c
LIMIT 10;
"
# Expected: Clean text, no HTML tags
```

### 2. Table Preservation
```bash
# Find table chunks
sqlite3 knowledge_base.db "
SELECT chunk_id, SUBSTR(content, 1, 200)
FROM chunks
WHERE chunk_type = 'table'
LIMIT 3;
"
# Expected: Markdown table format with | separators
```

### 3. Code Block Preservation
```bash
# Find code chunks
sqlite3 knowledge_base.db "
SELECT chunk_id, SUBSTR(content, 1, 200)
FROM chunks
WHERE chunk_type = 'code'
LIMIT 3;
"
# Expected: Code preserved with formatting
```

### 4. Header Hierarchy
```bash
# Check header tracking
sqlite3 knowledge_base.db "
SELECT chunk_id, parent_headers
FROM chunks
WHERE parent_headers IS NOT NULL
LIMIT 5;
"
# Expected: JSON array of parent headers
```

### 5. Idempotency
```bash
# First parse
python -m knowledge_base.cli parse
COUNT1=$(sqlite3 knowledge_base.db "SELECT COUNT(*) FROM chunks;")

# Second parse
python -m knowledge_base.cli parse
COUNT2=$(sqlite3 knowledge_base.db "SELECT COUNT(*) FROM chunks;")

[ "$COUNT1" = "$COUNT2" ] && echo "PASS: Idempotent" || echo "FAIL"
```

## Unit Tests

```python
# tests/test_chunking.py
import pytest
from knowledge_base.chunking.html_chunker import HTMLChunker

def test_basic_chunking():
    chunker = HTMLChunker(max_chunk_size=500)
    html = "<p>Test content</p>"
    chunks = chunker.chunk(html, "page_123")
    assert len(chunks) >= 1
    assert "Test content" in chunks[0].content

def test_table_preserved():
    chunker = HTMLChunker()
    html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
    chunks = chunker.chunk(html, "page_123")
    assert any(c.chunk_type == "table" for c in chunks)

def test_code_preserved():
    chunker = HTMLChunker()
    html = '<ac:structured-macro ac:name="code"><ac:plain-text-body>print("hello")</ac:plain-text-body></ac:structured-macro>'
    chunks = chunker.chunk(html, "page_123")
    assert any(c.chunk_type == "code" for c in chunks)
```

## Success Criteria

- [ ] All pages have at least 1 chunk
- [ ] No HTML tags in chunk content
- [ ] Tables converted to markdown
- [ ] Code blocks preserved
- [ ] Average chunk size within limits
- [ ] Re-parse produces same chunks
