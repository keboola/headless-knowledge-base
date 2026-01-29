# Phase 1: Infrastructure Setup - Specification

## Goal
Prepare the environment and dependencies for Graphiti and the chosen graph databases (Kuzu for dev, Neo4j for prod).

## Tasks

### 1.1 Add Dependencies
Update `pyproject.toml` to include:
- `graphiti-core[anthropic,kuzu]>=0.26.0`
- `neo4j>=5.26.0` (for production usage)

### 1.2 Local Development Setup
- Configure Kuzu as the default for local development.
- Ensure data storage path (`data/kuzu_graph/`) is configured.

### 1.3 Docker Compose (Optional/Prod)
- Add Neo4j service to `docker-compose.yml` for production-like testing.
- Use profiles (e.g., `profiles: [neo4j]`) to avoid starting it by default.

### 1.4 Configuration
Update `src/knowledge_base/config.py` with new settings:
- `GRAPH_BACKEND`: "kuzu" (default) or "neo4j".
- `GRAPH_KUZU_PATH`: Path to local Kuzu storage.
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`.
- `GRAPHITI_GROUP_ID`: For multi-tenancy support.

## Success Criteria
- Dependencies install clean.
- `config.py` has all necessary variables.
- Docker compose can start Neo4j.
