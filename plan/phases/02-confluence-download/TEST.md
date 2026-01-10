# Phase 02: Confluence Download - Test Plan

## Quick Verification

```bash
# Ensure services are running
docker-compose up -d

# Run download for a small test space
python -m knowledge_base.cli download --spaces=TEST --verbose

# Check database
sqlite3 knowledge_base.db "SELECT COUNT(*) FROM raw_pages;"
# Expected: Number of pages in TEST space
```

## Functional Tests

### 1. Authentication
```bash
# Test connection
python -c "
from knowledge_base.confluence.client import ConfluenceClient
import asyncio

async def test():
    client = ConfluenceClient()
    spaces = await client.get_spaces()
    print(f'Connected! Found {len(spaces)} spaces')

asyncio.run(test())
"
# Expected: Lists available spaces
```

### 2. Page Download
```bash
# Download and verify
python -m knowledge_base.cli download --spaces=TEST

# Check stored content
sqlite3 knowledge_base.db "
SELECT page_id, title, LENGTH(html_content) as content_size
FROM raw_pages
LIMIT 5;
"
# Expected: Pages with non-zero content size
```

### 3. Incremental Sync
```bash
# First download
python -m knowledge_base.cli download --spaces=TEST

# Record count
COUNT1=$(sqlite3 knowledge_base.db "SELECT COUNT(*) FROM raw_pages;")

# Second download (should be fast, no changes)
time python -m knowledge_base.cli download --spaces=TEST

# Verify same count
COUNT2=$(sqlite3 knowledge_base.db "SELECT COUNT(*) FROM raw_pages;")
[ "$COUNT1" = "$COUNT2" ] && echo "PASS: Idempotent" || echo "FAIL"
```

### 4. Rate Limiting
```bash
# Watch for rate limit handling in verbose mode
python -m knowledge_base.cli download --spaces=ENG --verbose 2>&1 | grep -i "rate\|retry\|429"
# Expected: No 429 errors (rate limiting works)
```

## Unit Tests

```python
# tests/test_confluence.py
import pytest
from knowledge_base.confluence.client import ConfluenceClient

@pytest.mark.asyncio
async def test_get_spaces():
    client = ConfluenceClient()
    spaces = await client.get_spaces()
    assert len(spaces) > 0

@pytest.mark.asyncio
async def test_get_page():
    client = ConfluenceClient()
    page = await client.get_page_content("123456")  # Known page ID
    assert page.html_content is not None
```

Run with:
```bash
pytest tests/test_confluence.py -v
```

## Success Criteria

- [ ] All configured spaces downloaded
- [ ] Page count matches Confluence
- [ ] HTML content stored correctly
- [ ] Permissions captured
- [ ] Re-run is idempotent (same result)
- [ ] No rate limit errors
