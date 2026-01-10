# Phase 01: Infrastructure

## Overview

Set up the foundational infrastructure: Docker services, FastAPI application, and basic health endpoints.

## Dependencies

- **Requires**: None (first phase)
- **Blocks**: All subsequent phases

## Deliverables

### Files to Create

```
ai-based-knowledge/
├── pyproject.toml              # Python dependencies
├── Dockerfile                  # Application container
├── docker-compose.yml          # All services
├── .env.example                # Configuration template
└── src/
    └── knowledge_base/
        ├── __init__.py
        ├── main.py             # FastAPI application
        ├── config.py           # Settings management
        └── api/
            ├── __init__.py
            └── health.py       # Health endpoints
```

### Docker Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| knowledge-base | Custom | 8000 | FastAPI app |
| chromadb | chromadb/chroma | 8001 | Vector database |
| redis | redis:7-alpine | 6379 | Task queue broker |
| ollama | ollama/ollama | 11434 | LLM server |

## Technical Specification

### pyproject.toml

```toml
[project]
name = "knowledge-base"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.1.0",
    "mypy>=1.8.0",
]
```

### config.py

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Knowledge Base"
    DEBUG: bool = False

    # ChromaDB
    CHROMA_HOST: str = "chromadb"
    CHROMA_PORT: int = 8000

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Ollama
    OLLAMA_BASE_URL: str = "http://ollama:11434"

    class Config:
        env_file = ".env"
```

### main.py

```python
from fastapi import FastAPI
from knowledge_base.api.health import router as health_router

app = FastAPI(title="Knowledge Base")
app.include_router(health_router)
```

### health.py

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/health/ready")
async def ready():
    # Check all dependencies
    return {"status": "ready", "services": {...}}
```

### docker-compose.yml

```yaml
version: "3.8"
services:
  knowledge-base:
    build: .
    ports:
      - "8000:8000"
    environment:
      - CHROMA_HOST=chromadb
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - chromadb
      - redis

  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - chroma_data:/chroma/chroma

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama

volumes:
  chroma_data:
  ollama_data:
```

## Definition of Done

- [ ] All files created and syntactically correct
- [ ] `docker-compose up -d` starts all services
- [ ] `curl http://localhost:8000/health` returns `{"status": "ok"}`
- [ ] `/health/ready` checks all service connections
- [ ] No errors in service logs
