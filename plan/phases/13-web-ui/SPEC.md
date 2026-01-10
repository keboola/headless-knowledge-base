# Phase 13: Web UI (Optional)

## Overview

Build a simple web interface for search, admin functions, and governance dashboards. This is optional - Slack remains the primary user interface.

## Dependencies

- **Requires**: Phase 6 (Search API), Phase 12 (Governance)
- **Blocks**: None (final phase)

## Deliverables

```
src/knowledge_base/
├── web/
│   ├── __init__.py
│   ├── app.py              # Web application setup
│   ├── routes.py           # Web routes
│   ├── templates/
│   │   ├── base.html       # Base template
│   │   ├── search.html     # Search interface
│   │   ├── admin.html      # Admin dashboard
│   │   └── governance.html # Governance dashboard
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── app.js
```

## Technical Specification

### Web Framework

```python
# Using FastAPI with Jinja2 templates
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})
```

### Search Interface

```html
<!-- templates/search.html -->
{% extends "base.html" %}
{% block content %}
<div class="search-container">
    <form id="search-form">
        <input type="text" name="query" placeholder="Ask a question..." />
        <button type="submit">Search</button>
    </form>

    <div id="results">
        <!-- Populated via JavaScript -->
    </div>
</div>

<script>
document.getElementById('search-form').onsubmit = async (e) => {
    e.preventDefault();
    const query = e.target.query.value;

    const response = await fetch('/api/v1/search', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query, top_k: 5})
    });

    const results = await response.json();
    renderResults(results);
};
</script>
{% endblock %}
```

### Admin Dashboard

```python
@app.get("/admin")
async def admin_dashboard(request: Request):
    """Admin dashboard showing system status."""
    stats = {
        "total_pages": await get_page_count(),
        "indexed_pages": await get_indexed_count(),
        "pending_sync": await get_pending_sync_count(),
        "last_sync": await get_last_sync_time(),
        "queue_depth": await get_celery_queue_depth(),
    }

    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "stats": stats}
    )

@app.post("/admin/sync")
async def trigger_sync():
    """Manually trigger Confluence sync."""
    from tasks.sync_tasks import full_sync
    task = full_sync.delay()
    return {"task_id": task.id, "status": "started"}

@app.post("/admin/reindex")
async def trigger_reindex():
    """Manually trigger full reindex."""
    from tasks.index_tasks import full_reindex
    task = full_reindex.delay()
    return {"task_id": task.id, "status": "started"}
```

### Governance Dashboard

```python
@app.get("/governance")
async def governance_dashboard(request: Request):
    """Governance dashboard showing content health."""
    detector = ObsoleteDetector()
    analyzer = GapAnalyzer()
    coverage = CoverageAnalyzer()

    data = {
        "obsolete_count": len(await detector.find_obsolete()),
        "gaps_count": len(await analyzer.find_gaps()),
        "coverage_matrix": await coverage.get_topic_coverage(),
        "recent_issues": await get_recent_governance_issues(limit=10),
    }

    return templates.TemplateResponse(
        "governance.html",
        {"request": request, **data}
    )
```

### Basic Authentication

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

security = HTTPBasic()

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials for protected routes."""
    correct_username = secrets.compare_digest(
        credentials.username,
        settings.admin_username
    )
    correct_password = secrets.compare_digest(
        credentials.password,
        settings.admin_password
    )

    if not (correct_username and correct_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return credentials.username

@app.get("/admin", dependencies=[Depends(verify_admin)])
async def admin_dashboard(request: Request):
    ...
```

### Static Assets

```css
/* static/css/style.css */
:root {
    --primary: #2563eb;
    --secondary: #64748b;
    --bg: #f8fafc;
    --card-bg: #ffffff;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    margin: 0;
    padding: 20px;
}

.search-container {
    max-width: 800px;
    margin: 0 auto;
}

.search-container input {
    width: 100%;
    padding: 16px;
    font-size: 18px;
    border: 2px solid #e2e8f0;
    border-radius: 8px;
}

.result-card {
    background: var(--card-bg);
    padding: 20px;
    margin: 16px 0;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.result-card h3 {
    margin: 0 0 8px 0;
    color: var(--primary);
}

.result-card .score {
    color: var(--secondary);
    font-size: 14px;
}
```

## API Integration

The web UI uses the existing API endpoints:

| Web Feature | API Endpoint |
|------------|--------------|
| Search | `POST /api/v1/search` |
| Stats | `GET /api/v1/stats` |
| Obsolete docs | `GET /api/v1/governance/obsolete` |
| Gaps | `GET /api/v1/governance/gaps` |
| Coverage | `GET /api/v1/governance/coverage` |
| Trigger sync | `POST /api/v1/admin/sync` |

## Definition of Done

- [ ] Search page works
- [ ] Admin dashboard shows stats
- [ ] Governance dashboard displays issues
- [ ] Basic authentication protects admin routes
- [ ] Responsive design works on mobile
