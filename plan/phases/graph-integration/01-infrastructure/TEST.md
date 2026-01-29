# Phase 1: Infrastructure Setup - Verification

## How to Verify

### 1. Dependencies
Run:
```bash
python -c "import graphiti_core; import neo4j; print('Success')"
```
**Expected**: Prints "Success".

### 2. Configuration
Run:
```bash
python -c "from src.knowledge_base.config import settings; print(settings.GRAPH_BACKEND)"
```
**Expected**: Prints "kuzu" (or configured default).

### 3. Neo4j (Docker)
Run:
```bash
docker compose --profile neo4j up -d
docker compose ps
```
**Expected**: Neo4j container is running and healthy.
(Teardown with `docker compose --profile neo4j down`)
