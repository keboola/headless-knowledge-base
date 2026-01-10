# Plan: Fix Recursion Errors in Markdown Converter

## Problem Analysis

### Root Cause
The `markdownify` library uses recursive DOM tree traversal (`process_tag()` → `process_element()` → `process_tag()`). Each nested HTML element adds one recursion level. Python's default limit is 1000.

### Current State
- 27 out of 449 pages (6%) failing with `RecursionError: maximum recursion depth exceeded`
- Errors occur in `html_to_markdown()` at `downloader.py:114`
- Failed pages have deeply nested HTML structures from Confluence

### Cyclical Reference Analysis
The user's concern about cyclical page references (Page A → Page B → Page A):
- **Not the cause here**: Confluence embeds (`<ac:include>`, `<ri:page>`) are already stripped by `_clean_confluence_html()` before markdownify runs
- The recursion is from deep HTML nesting WITHIN a single page, not cross-page references
- However, BeautifulSoup DOM could theoretically have cyclical references from malformed HTML - we should guard against this

## Solution Options Evaluated

| Option | Approach | Pros | Cons | Verdict |
|--------|----------|------|------|---------|
| 1 | `sys.setrecursionlimit(3000)` | Simple one-liner | Stack overflow risk, arbitrary | Buffer only |
| 2 | Try/except wrapper | Safe, no crashes | Loses formatting silently | Safety net only |
| 3 | Pre-process HTML depth limit | Fixes root cause, predictable | Minor structure changes | **Primary fix** |
| 4 | Iterative markdownify fork | No limits | Major rewrite, maintain fork | Overkill |

## Recommended Solution: Defense in Depth

Implement a **3-layer protection** strategy:

### Layer 1: HTML Depth Limiter (Primary Fix)
Pre-process HTML to flatten excessive nesting before conversion. Also detect and break any cyclical DOM references.

```python
from bs4 import BeautifulSoup, Tag

MAX_NESTING_DEPTH = 100  # Safe margin below recursion limit

def limit_html_depth(html: str, max_depth: int = MAX_NESTING_DEPTH) -> str:
    """
    Flatten HTML that exceeds max nesting depth.
    Also detects/breaks cyclical parent references.
    """
    soup = BeautifulSoup(html, 'html.parser')
    seen_ids = set()  # For cycle detection

    def flatten_deep_nodes(element, current_depth=0):
        if not isinstance(element, Tag):
            return

        for child in list(element.children):
            # Cycle detection using object id
            child_id = id(child)
            if child_id in seen_ids:
                # Break cycle by removing the node
                if hasattr(child, 'decompose'):
                    child.decompose()
                continue
            seen_ids.add(child_id)

            if current_depth >= max_depth:
                # Extract text content, remove nested structure
                if hasattr(child, 'get_text'):
                    text = child.get_text(separator=' ', strip=True)
                    child.replace_with(text)
            else:
                flatten_deep_nodes(child, current_depth + 1)

    flatten_deep_nodes(soup)
    return str(soup)
```

### Layer 2: Recursion Limit Increase (Buffer)
Temporarily increase limit during conversion for edge cases just under threshold.

```python
import sys
from contextlib import contextmanager

@contextmanager
def increased_recursion_limit(limit: int = 2000):
    """Temporarily increase recursion limit."""
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, limit))
    try:
        yield
    finally:
        sys.setrecursionlimit(old_limit)
```

### Layer 3: Graceful Fallback (Safety Net)
Catch any remaining errors and provide degraded but usable output.

```python
def html_to_markdown(html_content: str) -> tuple[str, bool]:
    """
    Convert HTML to markdown with fallback.
    Returns (markdown_content, conversion_succeeded).
    """
    try:
        # Clean Confluence-specific markup
        html_content = _clean_confluence_html(html_content)

        # Layer 1: Limit nesting depth and break cycles
        safe_html = limit_html_depth(html_content)

        # Layer 2: Increase limit temporarily
        with increased_recursion_limit(2000):
            markdown = md(safe_html, heading_style="ATX", bullets="-", ...)

        return _clean_markdown(markdown), True

    except RecursionError as e:
        # Layer 3: Fallback to plain text extraction
        logger.warning(f"Markdown conversion failed: {e}")
        soup = BeautifulSoup(html_content, 'html.parser')
        plain_text = soup.get_text(separator='\n\n', strip=True)
        return f"[Content extracted as plain text due to complex formatting]\n\n{plain_text}", False
```

## Implementation Plan

### Files to Modify

1. **`src/knowledge_base/confluence/markdown_converter.py`**
   - Add `limit_html_depth()` function with cycle detection
   - Add `increased_recursion_limit()` context manager
   - Modify `html_to_markdown()` to return success flag
   - Add plain text fallback

2. **`src/knowledge_base/confluence/downloader.py`**
   - Update `_create_page()` and `_update_page()` to handle conversion status
   - Log warnings for pages using fallback conversion

### Step-by-Step Implementation

1. Add `limit_html_depth()` function to markdown_converter.py
2. Add `increased_recursion_limit()` context manager
3. Update `html_to_markdown()` signature to return tuple
4. Add try/except with plain text fallback
5. Update downloader to handle new return type
6. Add logging for degraded conversions

### Testing

Test with the 27 failing page IDs from production:
```
85885176, 1611628630, 2230484997, 2294480914, 2317582367,
2340978878, 2366111854, 2386034766, 2399010914, 2416115727,
2434269185, 2458124306, 2477260890, 2496331822, 2513272833,
2530377770, 2549022750, 2567962631, 2578415780, 2595717139,
2617376847, 2636415014, 2658238518, 2682617898, 2706276353,
2732097537, 2759163926
```

## Expected Outcome

| Metric | Before | After |
|--------|--------|-------|
| Pages synced | 422/449 (94%) | 449/449 (100%) |
| Full markdown quality | 422 | ~422 |
| Plain text fallback | 0 | ~27 |
| Process crashes | Risk | None |

## Rollback Plan

If issues arise, revert `markdown_converter.py` changes. The fallback is additive and doesn't break existing behavior.
