# Phase 01: Infrastructure - Test Plan

## Quick Verification

```bash
# Start all services
docker-compose up -d

# Wait for services to be ready
sleep 10

# Test health endpoint
curl http://localhost:8000/health
# Expected: {"status": "ok"}

# Test readiness endpoint
curl http://localhost:8000/health/ready
# Expected: {"status": "ready", "services": {"chromadb": "ok", "redis": "ok", "ollama": "ok"}}
```

## Service Checks

### 1. FastAPI Application
```bash
# Check container is running
docker-compose ps knowledge-base
# Expected: State = Up

# Check logs for errors
docker-compose logs knowledge-base | grep -i error
# Expected: No errors
```

### 2. ChromaDB
```bash
# Check container
docker-compose ps chromadb
# Expected: State = Up

# Test ChromaDB API
curl http://localhost:8001/api/v1/heartbeat
# Expected: {"nanosecond heartbeat": ...}
```

### 3. Redis
```bash
# Check container
docker-compose ps redis
# Expected: State = Up

# Test Redis connection
docker-compose exec redis redis-cli ping
# Expected: PONG
```

### 4. Ollama
```bash
# Check container
docker-compose ps ollama
# Expected: State = Up

# Test Ollama API
curl http://localhost:11434/api/tags
# Expected: {"models": [...]}
```

## Automated Tests

```python
# tests/test_health.py
import pytest
from httpx import AsyncClient
from knowledge_base.main import app

@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
```

Run with:
```bash
pytest tests/test_health.py -v
```

## Failure Scenarios

| Scenario | Expected Behavior |
|----------|-------------------|
| ChromaDB down | `/health/ready` returns `{"chromadb": "error"}` |
| Redis down | `/health/ready` returns `{"redis": "error"}` |
| Ollama down | `/health/ready` returns `{"ollama": "error"}` |

## Success Criteria

- [ ] All 4 containers running
- [ ] `/health` returns 200
- [ ] `/health/ready` shows all services "ok"
- [ ] No errors in any service logs
- [ ] Pytest tests pass
