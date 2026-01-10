# Phase 02: Confluence Download

## Overview

Download all pages from configured Confluence spaces to local storage for processing.

## Dependencies

- **Requires**: Phase 01 (Infrastructure)
- **Blocks**: Phase 03 (Content Parsing)

## Deliverables

```
src/knowledge_base/
├── confluence/
│   ├── __init__.py
│   ├── client.py           # Confluence API client
│   ├── downloader.py       # Page fetcher with rate limiting
│   └── models.py           # Page data models
├── db/
│   ├── __init__.py
│   ├── database.py         # SQLite connection
│   └── models.py           # SQLAlchemy models (RawPage)
└── cli.py                  # CLI commands
```

## Technical Specification

### Confluence Client

```python
class ConfluenceClient:
    """Async Confluence API client with rate limiting."""

    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self.rate_limiter = RateLimiter(requests_per_second=5)

    async def get_all_pages(self, space_key: str) -> AsyncIterator[Page]:
        """Fetch all pages from a space with pagination."""

    async def get_page_content(self, page_id: str) -> PageContent:
        """Fetch full page content including body."""

    async def get_page_permissions(self, page_id: str) -> list[Permission]:
        """Fetch page-level permissions."""
```

### File Storage

**Markdown files with randomized names** (like Google Photos):
- All files stored in flat directory: `data/pages/`
- Random 16-char hex filenames: `a7b3c9d2e1f4a8b6.md`
- No folder structure - search is via metadata
- Content converted from HTML to Markdown

```
data/pages/
├── a7b3c9d2e1f4a8b6.md
├── f1e2d3c4b5a69870.md
├── 0123456789abcdef.md
└── ...
```

### Database Model

```python
class RawPage(Base):
    __tablename__ = "raw_pages"

    id: int                     # Auto-increment
    page_id: str                # Confluence page ID (unique)
    space_key: str              # Space key
    title: str                  # Page title
    file_path: str              # Path to .md file (e.g., "data/pages/a7b3c9d2.md")
    author: str                 # Last modifier (account ID)
    author_name: str            # Last modifier display name (human-readable)
    url: str                    # Confluence URL
    created_at: datetime        # Page creation date (first version)
    updated_at: datetime        # Page last update (current version)
    downloaded_at: datetime     # When we downloaded it
    version_number: int         # Current version number
    permissions: str            # JSON array of permissions
    status: str                 # "active" or "deleted"
```

### CLI Command

```bash
# Download all pages from specified spaces
python -m knowledge_base.cli download --spaces=ENG,HR,DOCS

# Download with verbose output
python -m knowledge_base.cli download --spaces=ENG --verbose

# Resume interrupted download
python -m knowledge_base.cli download --spaces=ENG --resume
```

### Rate Limiting Strategy

```python
from tenacity import retry, wait_exponential, stop_after_attempt

@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5)
)
async def fetch_with_retry(self, url: str):
    response = await self.client.get(url)
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        raise RateLimitError(retry_after)
    return response
```

### Sync Strategy (One-Time + Manual Rebase)

**Initial sync**: Run once to download all content from Confluence.

**Manual rebase**: Call when you want to refresh from Confluence (e.g., major updates).

```bash
# Initial full sync
python -m knowledge_base.cli sync --full

# Manual rebase (when needed)
python -m knowledge_base.cli sync --rebase
```

### Staleness Detection

Documents 2+ years old are flagged as potentially stale in metadata:

```python
class RawPage(Base):
    # ... existing fields ...
    is_potentially_stale: bool  # True if updated_at > 2 years ago
    staleness_reason: str | None  # "Not updated in X days"

def calculate_staleness(updated_at: datetime) -> tuple[bool, str | None]:
    age_days = (datetime.utcnow() - updated_at).days
    if age_days > 730:  # 2 years
        return True, f"Not updated in {age_days} days"
    return False, None
```

### Complete Extraction Checklist

Ensure we capture EVERYTHING from Confluence:

| Data | Extracted | Stored In |
|------|-----------|-----------|
| Page title | ✅ | raw_pages.title |
| Markdown content | ✅ | .md file (random name) |
| File path | ✅ | raw_pages.file_path |
| Author (account ID) | ✅ | raw_pages.author |
| Author (display name) | ✅ | raw_pages.author_name |
| Created date | ✅ | raw_pages.created_at |
| Updated date | ✅ | raw_pages.updated_at |
| Version number | ✅ | raw_pages.version_number |
| Page URL | ✅ | raw_pages.url |
| Space key | ✅ | raw_pages.space_key |
| Permissions | ✅ | raw_pages.permissions (JSON) |
| Labels/tags | ✅ | raw_pages.labels (JSON) |
| Parent page ID | ✅ | raw_pages.parent_id |
| Attachments | ✅ | raw_pages.attachments (JSON list) |
| Comments | ⚠️ Optional | raw_pages.comments (JSON) |

### Governance Metadata

Separate table for governance fields (extracted from Confluence labels):

```python
class GovernanceMetadata(Base):
    __tablename__ = "governance_metadata"

    page_id: str                    # FK to raw_pages
    owner: str | None               # Contact person (from label: owner:john.doe)
    reviewed_by: str | None         # Last reviewer (from label: reviewed-by:jane)
    reviewed_at: datetime | None    # Review date (from label: reviewed:2024-01-15)
    classification: str             # public/internal/confidential (from label)
    doc_type: str | None            # policy/procedure/guideline/general
```

**Already in raw_pages (from Confluence API):**
- `author` - who last modified
- `created_at` - when created
- `updated_at` - when last modified
- `is_potentially_stale` - True if 2+ years old

**Label extraction:**

```python
def extract_governance_from_labels(labels: list[str]) -> GovernanceMetadata:
    """Extract governance fields from Confluence labels."""
    governance = {}
    for label in labels:
        if label.startswith("owner:"):
            governance["owner"] = label.split(":", 1)[1]
        elif label.startswith("reviewed-by:"):
            governance["reviewed_by"] = label.split(":", 1)[1]
        elif label.startswith("reviewed:"):
            governance["reviewed_at"] = parse_date(label.split(":", 1)[1])
        elif label in ("public", "internal", "confidential"):
            governance["classification"] = label
        elif label in ("policy", "procedure", "guideline"):
            governance["doc_type"] = label
    return GovernanceMetadata(**governance)
```

### Rebase Function

```python
async def rebase_from_confluence(space_keys: list[str] | None = None):
    """
    Manual rebase: re-download all pages from Confluence.
    Preserves feedback/quality scores (linked by page_id).
    """
    downloader = ConfluenceDownloader()
    spaces = space_keys or settings.confluence_space_keys

    for space_key in spaces:
        logger.info(f"Rebasing space: {space_key}")
        await downloader.sync_space(space_key, force_update=True)

    # Re-run chunking and indexing
    await reindex_all_pages()
```

## Configuration

```bash
CONFLUENCE_URL=https://keboola.atlassian.net
CONFLUENCE_USERNAME=service-account@keboola.com
CONFLUENCE_API_TOKEN=xxx
CONFLUENCE_SPACE_KEYS=ENG,HR,DOCS
```

## Definition of Done

- [ ] Confluence client connects and authenticates
- [ ] All pages from configured spaces downloaded
- [ ] Pages saved as .md files with random names in flat directory
- [ ] Metadata stored in SQLite (file_path, title, etc.)
- [ ] Rate limiting prevents API throttling
- [ ] Idempotent: re-run updates existing, adds new
- [ ] Deleted pages marked (not removed)
