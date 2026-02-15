# ADR-0009: Neo4j + Graphiti as Knowledge Store

## Status
Accepted

## Date
2026-02-13

## Context
The original architecture used ChromaDB for vector storage (ADR-0002) and designated it as source of truth (ADR-0005), with NetworkX for in-memory graph traversal. This had limitations:
- NetworkX graph was ephemeral (lost on restart)
- No temporal tracking of entity relationships
- ChromaDB lacked native graph traversal capabilities
- No persistent knowledge graph for multi-hop queries

## Decision
We adopted **Graphiti-core** framework with **Neo4j 5.26** as the graph database backend for all environments.

- Graphiti provides temporal knowledge graph capabilities (bi-temporal model)
- Neo4j provides persistent, queryable graph storage via Bolt protocol
- Entity extraction uses Claude Sonnet or Gemini Flash via Graphiti
- Hybrid retrieval combines semantic search with graph traversal
- ChromaDB is deprecated; Graphiti handles all knowledge storage and search

## Rationale

### Why Graphiti?
- Temporal-aware knowledge graphs with bi-temporal model
- Built-in hybrid retrieval (semantic + BM25 + graph)
- Incremental updates without full recomputation
- Active development (22k+ GitHub stars)

### Why Neo4j?
- Enterprise-grade graph database with mature tooling
- Bolt protocol for efficient client communication
- APOC plugin for advanced graph operations (required by Graphiti)
- Neodash for visual graph dashboards
- Community Edition is free and sufficient

### Why not keep ChromaDB?
- Graphiti handles both vector storage and graph storage internally
- Eliminates dual-storage sync complexity
- Single source of truth for all knowledge data
- Better multi-hop query support via native graph traversal

## Consequences

### Positive
- Persistent knowledge graph survives restarts
- Temporal tracking of entity relationships
- Multi-hop queries via native graph traversal
- Unified storage and search through Graphiti
- Visual dashboards via Neodash

### Negative
- Neo4j requires dedicated GCE VM (additional infrastructure)
- Higher memory requirements than ChromaDB
- LLM costs for entity extraction during ingestion

### Migration
- Full migration documented in docs/GRAPH_DATABASE_PLAN.md
- Clean cutover approach: re-ingest all documents through Graphiti
- Old NetworkX and ChromaDB code deprecated but not yet fully removed from codebase

## Supersedes
- [ADR-0002](0002-vector-store-chromadb-on-cloudrun.md) - ChromaDB on Cloud Run
- [ADR-0005](0005-chromadb-source-of-truth.md) - ChromaDB as Source of Truth

## References
- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Neo4j Documentation](https://neo4j.com/docs/)
- [docs/GRAPH_DATABASE_PLAN.md](../GRAPH_DATABASE_PLAN.md) - Migration plan
- [docs/NEO4J_FIX_DOCUMENTATION.md](../NEO4J_FIX_DOCUMENTATION.md) - Infrastructure setup
