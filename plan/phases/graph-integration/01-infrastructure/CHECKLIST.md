# Phase 1: Infrastructure Setup - Checklist

## Dependencies
- [x] Edit `pyproject.toml` to add `graphiti-core` and `neo4j`.
- [x] Run `pip install .` or equivalent to update lock/environment.
- [x] Verify `import graphiti_core` works in shell.

## Configuration
- [x] Add `GRAPH_BACKEND`, `GRAPH_KUZU_PATH` to `.env.example`.
- [x] Add `NEO4J_*` vars to `.env.example`.
- [x] Update `src/knowledge_base/config.py` to load these variables.

## Docker
- [x] Add `neo4j` service to `docker-compose.yml`.
- [x] Configure `NEO4J_AUTH` and ports.
- [ ] Test startup with `docker compose --profile neo4j up`. (requires Docker)

## Storage
- [x] Ensure `data/kuzu_graph` is in `.gitignore` (if not already covered).
