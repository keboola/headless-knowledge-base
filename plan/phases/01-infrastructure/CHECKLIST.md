# Phase 01: Infrastructure - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Ensure Docker is installed and running
- [ ] Create `.env` file from `.env.example`

## Implementation Tasks

### 1. Project Setup
- [ ] Create `pyproject.toml` with dependencies
- [ ] Create `src/knowledge_base/__init__.py`
- [ ] Install dependencies: `pip install -e .`

### 2. Configuration
- [ ] Create `src/knowledge_base/config.py` with Settings class
- [ ] Create `.env.example` with all config variables
- [ ] Verify settings load correctly

### 3. FastAPI Application
- [ ] Create `src/knowledge_base/main.py` with FastAPI app
- [ ] Create `src/knowledge_base/api/__init__.py`
- [ ] Create `src/knowledge_base/api/health.py` with endpoints

### 4. Health Endpoints
- [ ] Implement `GET /health` - basic health check
- [ ] Implement `GET /health/ready` - dependency checks
- [ ] Add ChromaDB connection check
- [ ] Add Redis connection check
- [ ] Add Ollama connection check

### 5. Docker Setup
- [ ] Create `Dockerfile` for the application
- [ ] Create `docker-compose.yml` with all services
- [ ] Configure volume mounts for persistence
- [ ] Set up service dependencies

### 6. Verification
- [ ] Run `docker-compose up -d`
- [ ] Verify all containers are running
- [ ] Test health endpoint
- [ ] Check logs for errors

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit with message: "feat(phase-01): infrastructure setup"
