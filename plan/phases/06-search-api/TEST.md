# Phase 06: Search API - Test Plan

## Quick Verification

```bash
# Basic search
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I request PTO?"}'

# Should return results with scores
```

## Functional Tests

### 1. Basic Search
```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "vacation policy", "top_k": 3}' | jq '.results | length'
# Expected: 3 (or fewer if less content)
```

### 2. Filter by Space
```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "onboarding",
    "filters": {"space_key": "HR"}
  }' | jq '.results[].metadata.space_key'
# Expected: All results show "HR"
```

### 3. Filter by Doc Type
```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "security",
    "filters": {"doc_type": "policy"}
  }' | jq '.results[].metadata.doc_type'
# Expected: All results show "policy"
```

### 4. Search Methods
```bash
# Vector only
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{"query": "PTO", "search_method": "vector"}' | jq '.search_method'

# BM25 only
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{"query": "PTO", "search_method": "bm25"}' | jq '.search_method'

# Hybrid (default)
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{"query": "PTO"}' | jq '.search_method'
```

### 5. Performance
```bash
# Measure response time
for i in {1..10}; do
  curl -s -X POST http://localhost:8000/api/v1/search \
    -d '{"query": "onboarding process"}' \
    -w "\n%{time_total}s\n" -o /dev/null
done
# Expected: < 0.5s average
```

### 6. Confluence URLs
```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{"query": "test", "top_k": 1}' | jq '.results[0].url'
# Expected: Valid Confluence URL
```

## Unit Tests

```python
# tests/test_search_api.py
import pytest
from httpx import AsyncClient
from knowledge_base.main import app

@pytest.mark.asyncio
async def test_basic_search():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search",
            json={"query": "test", "top_k": 5}
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "took_ms" in data

@pytest.mark.asyncio
async def test_search_with_filters():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search",
            json={
                "query": "policy",
                "filters": {"doc_type": "policy"}
            }
        )
        assert response.status_code == 200
        for result in response.json()["results"]:
            assert result["metadata"]["doc_type"] == "policy"

@pytest.mark.asyncio
async def test_search_invalid_method():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search",
            json={"query": "test", "search_method": "invalid"}
        )
        assert response.status_code == 422  # Validation error
```

## Success Criteria

- [ ] Search returns relevant results
- [ ] Filters work correctly
- [ ] All search methods functional
- [ ] Confluence URLs valid
- [ ] Response time < 500ms
- [ ] Error handling for empty results
