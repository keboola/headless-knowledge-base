# Phase 13: Web UI - Test Plan

## Quick Verification

```bash
# Start the server
python -m uvicorn knowledge_base.main:app --reload

# Open in browser
open http://localhost:8000/
```

## Functional Tests

### 1. Search Page
```bash
# Open search page
curl http://localhost:8000/

# Should return HTML with:
# - Search form
# - Results container
# - Navigation

# Test search via UI:
# 1. Open http://localhost:8000/
# 2. Type "vacation policy"
# 3. Click Search
# 4. Should see results with titles and snippets
```

### 2. Admin Dashboard (Auth Required)
```bash
# Without auth - should return 401
curl http://localhost:8000/admin
# Expected: 401 Unauthorized

# With auth
curl -u admin:password http://localhost:8000/admin

# Should return HTML with:
# - Total pages count
# - Indexed pages count
# - Last sync time
# - Sync/Reindex buttons
```

### 3. Trigger Sync
```bash
# Via UI or curl
curl -u admin:password -X POST http://localhost:8000/admin/sync

# Expected:
# {"task_id": "abc123", "status": "started"}
```

### 4. Governance Dashboard
```bash
curl -u admin:password http://localhost:8000/governance

# Should show:
# - Obsolete document count
# - Documentation gaps
# - Coverage matrix
# - Recent issues
```

### 5. Static Assets
```bash
# CSS should load
curl http://localhost:8000/static/css/style.css
# Should return CSS content

# JS should load
curl http://localhost:8000/static/js/app.js
# Should return JavaScript content
```

### 6. Mobile Responsiveness
```bash
# Test in browser dev tools:
# 1. Open http://localhost:8000/
# 2. Open Developer Tools (F12)
# 3. Toggle device toolbar
# 4. Select mobile device (iPhone, Pixel)
# 5. Verify layout adjusts properly
```

## Unit Tests

```python
# tests/test_web_ui.py
import pytest
from fastapi.testclient import TestClient
from knowledge_base.web.app import app

client = TestClient(app)

def test_search_page_loads():
    response = client.get("/")
    assert response.status_code == 200
    assert "search" in response.text.lower()

def test_admin_requires_auth():
    response = client.get("/admin")
    assert response.status_code == 401

def test_admin_with_auth():
    response = client.get(
        "/admin",
        auth=("admin", "password")
    )
    assert response.status_code == 200
    assert "dashboard" in response.text.lower()

def test_governance_requires_auth():
    response = client.get("/governance")
    assert response.status_code == 401

def test_governance_with_auth():
    response = client.get(
        "/governance",
        auth=("admin", "password")
    )
    assert response.status_code == 200

def test_static_css_loads():
    response = client.get("/static/css/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]

def test_static_js_loads():
    response = client.get("/static/js/app.js")
    assert response.status_code == 200

def test_trigger_sync_requires_auth():
    response = client.post("/admin/sync")
    assert response.status_code == 401

def test_trigger_sync_with_auth():
    response = client.post(
        "/admin/sync",
        auth=("admin", "password")
    )
    assert response.status_code == 200
    assert "task_id" in response.json()
```

## Integration Test

```python
@pytest.mark.asyncio
async def test_search_flow():
    """Test full search flow via web UI."""
    # 1. Load search page
    response = client.get("/")
    assert response.status_code == 200

    # 2. Perform search via API (simulating JS)
    search_response = client.post(
        "/api/v1/search",
        json={"query": "vacation policy", "top_k": 5}
    )
    assert search_response.status_code == 200
    results = search_response.json()
    assert len(results) > 0

    # 3. Submit feedback
    feedback_response = client.post(
        "/api/v1/feedback",
        json={
            "query_id": results[0].get("query_id"),
            "page_id": results[0]["page_id"],
            "feedback_type": "explicit",
            "is_positive": True
        }
    )
    assert feedback_response.status_code == 200

@pytest.mark.asyncio
async def test_admin_stats_accurate():
    """Verify admin dashboard shows accurate stats."""
    # Get stats via API
    api_stats = client.get("/api/v1/stats").json()

    # Get admin page
    admin_response = client.get(
        "/admin",
        auth=("admin", "password")
    )

    # Verify stats appear in HTML
    assert str(api_stats["total_pages"]) in admin_response.text
```

## Browser Tests (Manual)

### Search Flow
1. Open http://localhost:8000/
2. Enter "How do I submit PTO?"
3. Verify results appear
4. Click thumbs up on a result
5. Verify feedback submitted (check network tab)

### Admin Flow
1. Open http://localhost:8000/admin
2. Enter credentials when prompted
3. Verify stats display
4. Click "Trigger Sync"
5. Verify task started message
6. Check Celery logs for task execution

### Governance Flow
1. Open http://localhost:8000/governance
2. Verify obsolete docs listed
3. Verify gaps displayed
4. Verify coverage matrix renders
5. Click on an issue to see details

## Success Criteria

- [ ] Search page loads and works
- [ ] Results render correctly
- [ ] Feedback buttons work
- [ ] Admin dashboard protected
- [ ] Admin stats accurate
- [ ] Sync/Reindex buttons trigger tasks
- [ ] Governance dashboard shows data
- [ ] CSS styles applied
- [ ] Mobile responsive
