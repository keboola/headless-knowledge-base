# Architecture Principles

This document defines the canonical architecture principles for the AI Knowledge Base system. All implementation decisions should align with these principles.

**Last Updated:** 2026-02-18

---

## Core Principles

### Principle 1: Neo4j + Graphiti is the Source of Truth for Knowledge

The **Graphiti temporal knowledge graph**, backed by **Neo4j 5.26**, is the primary and authoritative store for all knowledge-related data. This includes:

- **Episodic nodes** - Document chunks stored as Graphiti episodes
- **Entity nodes** - People, teams, tools, concepts extracted by LLM
- **Relationship edges** - Typed, weighted connections between entities
- **Vector embeddings** - Stored natively in Neo4j for semantic search
- **Temporal metadata** - Bi-temporal model (valid time + transaction time)

**Data stored per episode in Neo4j:**

| Field | Storage | Description |
|-------|---------|-------------|
| `uuid` | Episodic node | Unique identifier for the episode |
| `name` | Episodic node | Episode name / chunk identifier |
| `content` | Episodic node | Full chunk text |
| `embedding` | Episodic node | Vector embedding for semantic search |
| `source_description` | Episodic node (JSON) | Structured metadata (see below) |
| `group_id` | Episodic node | Multi-tenancy group identifier |
| `created_at` | Episodic node | Bi-temporal: transaction time |
| `valid_at` | Episodic node | Bi-temporal: when content was valid |

**Metadata stored in `source_description` (JSON):**

| Field | Type | Description |
|-------|------|-------------|
| `page_id` | string | Confluence page identifier |
| `page_title` | string | Human-readable title |
| `space_key` | string | Confluence space key |
| `url` | string | Link to original document |
| `author` | string | Content author |
| `created_at` | ISO datetime | When content was created |
| `updated_at` | ISO datetime | Last modification time |
| `chunk_id` | string | Unique chunk identifier |
| `chunk_type` | string | text, code, table, list |
| `quality_score` | float | 0-100, updated on feedback |
| `owner` | string | Content owner (governance) |
| `classification` | string | public, internal, confidential |
| `doc_type` | string | policy, how-to, reference, FAQ |
| `deleted` | boolean | Soft-delete flag |

---

### Principle 2: SQLite is for Local Metadata and Feedback Only

SQLite (via SQLAlchemy 2.0 async) stores **only** data that is local to the application instance and not part of the knowledge graph:

1. **Page sync metadata** - Confluence page tracking (RawPage, sync state)
2. **Indexing checkpoints** - Resume state for crash-resilient pipeline (IndexingCheckpoint)
3. **Governance metadata** - Ownership and review tracking
4. **User feedback** - Explicit feedback (helpful, incorrect, outdated, confusing)
5. **Behavioral signals** - Implicit signals (thanks, frustration, reactions)

**SQLite does NOT store:**
- Document content or chunks (these live in Neo4j as episodes)
- Vector embeddings (stored natively in Neo4j)
- Entity or relationship data (managed by Graphiti in Neo4j)
- Search indices (Graphiti handles all search internally)

---

### Principle 3: No Duplication of Source of Truth

Each piece of data lives in **exactly one place**:

| Data Type | Location | Rationale |
|-----------|----------|-----------|
| Document chunks | Neo4j (Graphiti episodes) | Primary knowledge store |
| Vector embeddings | Neo4j (Graphiti episodes) | Semantic search via Graphiti |
| Entities + relationships | Neo4j (Graphiti nodes/edges) | Knowledge graph structure |
| Quality scores | Neo4j (episode metadata) | Filter/boost during search |
| Governance info | Neo4j (episode metadata) | Filter during search |
| Page sync state | SQLite | Local operational data |
| Indexing checkpoints | SQLite (persisted to GCS) | Pipeline resume state |
| User feedback | SQLite | Feedback tracking and score updates |
| Behavioral signals | SQLite | Analytics and implicit signals |

**Why no duplication?**
- Eliminates sync complexity between stores
- Single source of truth prevents inconsistencies
- Simpler mental model for developers
- Graphiti manages its own indices and constraints

---

### Principle 4: Quality Scores are Managed via Graphiti Metadata

Quality scores are stored in Neo4j episode metadata and updated through the application layer:

```
1. New chunk ingested via Graphiti
   -> quality_score: 100.0 in episode source_description

2. User gives feedback
   -> Update episode metadata in Neo4j
   -> Log feedback to SQLite (for analytics)

3. Search query
   -> Graphiti hybrid search returns results
   -> Post-search quality boost applied (weight: 0.2)
```

**Score adjustments:**

| Feedback Type | Score Change |
|---------------|--------------|
| helpful | +2 |
| confusing | -5 |
| outdated | -15 |
| incorrect | -25 |

---

## System Architecture

```
                         +-------------------------------------+
                         |           SLACK BOT                 |
                         |       (Cloud Run - HTTP mode)       |
                         +-------------------------------------+
                              |                     |
                              | Questions /         | Feedback /
                              | Knowledge Queries   | Reactions
                              v                     v
+----------------------------------------------+  +---------------------------+
|               NEO4J 5.26 + GRAPHITI           |  |         SQLITE            |
|            (Source of Truth)                   |  |    (Local Metadata)       |
+----------------------------------------------+  +---------------------------+
|                                                |  |                           |
|  Episodic Nodes (document chunks):             |  |  Tables:                  |
|  - uuid, name, content                         |  |  - raw_page               |
|  - embedding (vector)                          |  |  - governance_metadata     |
|  - source_description (JSON metadata)          |  |  - user_feedback           |
|  - group_id (multi-tenancy)                    |  |  - behavioral_signal       |
|  - created_at, valid_at (bi-temporal)          |  |                           |
|                                                |  |  Purpose:                 |
|  Entity Nodes (extracted by LLM):              |  |  - Page sync tracking     |
|  - People, Teams, Tools, Concepts              |  |  - Governance state       |
|  - Auto-extracted via Claude/Gemini            |  |  - Feedback logging       |
|                                                |  |  - Behavioral analytics   |
|  Relationship Edges:                           |  |                           |
|  - Typed, weighted, temporal                   |  +---------------------------+
|  - Managed by Graphiti framework               |
|                                                |
|  Search: Hybrid (semantic + BM25 + graph)      |
|  Protocol: Bolt (port 7687)                    |
|  Plugins: APOC (required by Graphiti)          |
+----------------------------------------------+
                              |
                   +----------+----------+
                   |                     |
                   v                     v
        +------------------+   +------------------+
        |     REDIS        |   |   CELERY WORKERS |
        |  (Task Queue)    |   |  (Background)    |
        +------------------+   +------------------+
```

---

## Data Flows

### Flow 1: Content Ingestion (Confluence Sync)

```
Confluence API
    |
    v
Download pages -> stored as .md files in data/pages/
    |
    v
Parse & chunk pages
    |
    v
Graphiti add_episode() / add_episode_bulk()
    |
    +-- LLM entity extraction (Claude Sonnet / Gemini Flash)
    +-- Embedding generation (sentence-transformers / Vertex AI)
    +-- Neo4j stores: episode node, entity nodes, relationship edges
    |
    v
Episode stored in Neo4j with metadata:
    source_description = JSON({
        page_id, page_title, space_key, url,
        author, updated_at, chunk_type, chunk_id,
        quality_score: 100.0,
        owner, classification, doc_type, ...
    })
```

**Bulk indexing:**
- Adaptive batch sizing: starts at 2, grows to max 20
- Concurrent processing with configurable semaphore (default: 5)
- Rate limit handling with exponential backoff and circuit breaker

### Pipeline Checkpoint Persistence

The indexing pipeline (Step 3 of Flow 1) can take 10-20+ hours due to LLM rate limits. To survive crashes, timeouts, and restarts, checkpoints are persisted to GCS after every indexed chunk.

```
Cloud Run Job container
    |
    +-- Local SQLite DB (./knowledge_base.db)
    |       |-- RawPage, Chunk tables (download/parse data)
    |       |-- IndexingCheckpoint table (indexed chunk_ids)
    |
    +-- GCS FUSE mount (/mnt/pipeline-state/)
            |-- prod-knowledge-base.db (persistent copy)
```

**Checkpoint flow per batch:**
1. Graphiti indexes 1-5 chunks via `add_episode_bulk()`
2. Raw aiosqlite writes checkpoints (bypasses SQLAlchemy connection pool)
3. `PRAGMA wal_checkpoint(TRUNCATE)` merges WAL data into main DB file
4. `shutil.copyfile` copies DB to GCS FUSE mount

**On restart:** Shell wrapper restores DB from FUSE mount. The pipeline queries `IndexingCheckpoint` to find already-indexed chunks and skips them.

**Key design choices** (see [ADR-0010](adr/0010-pipeline-checkpoint-persistence.md)):
- Raw aiosqlite (not SQLAlchemy) for checkpoint writes -- avoids connection pool lock contention
- SQLAlchemy NullPool -- connections close immediately, no WAL lock retention
- WAL checkpoint before copy -- ensures copied DB file contains all data
- `ConfluenceDownloader(index_to_graphiti=False)` -- prevents Graphiti indexing during download while session is open

### Flow 2: Question Answering

```
User Question (via Slack)
    |
    v
GraphitiRetriever.search_chunks()
    |
    v
Graphiti.search(
    query=question,
    num_results=30,       # Over-fetch for filtering
    group_ids=[group_id]  # Multi-tenancy
)
    |
    +-- Semantic similarity (vector embeddings in Neo4j)
    +-- BM25 keyword matching (Graphiti internal)
    +-- Graph traversal (entity relationships)
    |
    v
Post-search processing:
    - Batch lookup episode content from Neo4j
    - Deduplicate by episode UUID
    - Filter by space_key, doc_type, quality_score
    - Apply quality boost (weight: 0.2)
    |
    v
LLM generates answer from top chunks (Claude)
    |
    v
Return answer + source links + feedback buttons
```

### Flow 3: Feedback Processing

```
User clicks "Incorrect"
    |
    +-----------------------------------+
    |                                   |
    v                                   v
Neo4j: Update episode metadata      SQLite: Insert user_feedback(
    source_description.quality_score      chunk_id,
    = old_score - 25                      feedback_type="incorrect",
                                          comment,
                                          suggested_correction,
                                          user_id, timestamp
                                      )
    |
    v
Notify content owner (if applicable)
via #knowledge-admins channel
```

### Flow 4: Behavioral Signal Capture

```
User says "thanks" in thread
    |
    v
SQLite: Insert behavioral_signal(
    chunk_ids=[...],
    signal_type="thanks",
    signal_value=0.4,
    user_id, timestamp
)
```

**Note:** Behavioral signals go to SQLite only (analytics). They do NOT update Neo4j quality scores -- only explicit feedback does.

### Flow 5: Graph Expansion

```
Initial search returns page_ids
    |
    v
Find common entities across results
    |
    v
Traverse graph to find additional
documents sharing those entities
    |
    v
Score by entity overlap count
    |
    v
Merge expanded results with original
```

Graph expansion is always enabled with Graphiti (`GRAPH_EXPANSION_ENABLED: true`). Graphiti's search natively leverages graph structure, so expansion is inherent in the hybrid retrieval.

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Knowledge Graph | Neo4j 5.26 Community + APOC | Graph storage, vector index, entity/relationship store |
| Graph Framework | Graphiti-core | Temporal knowledge graph, entity extraction, hybrid search |
| Graph Protocol | Bolt (port 7687) | Neo4j wire protocol |
| Metadata DB | SQLite + SQLAlchemy 2.0 (async, NullPool) | Page sync state, checkpoints, feedback, behavioral signals |
| Checkpoint Storage | GCS bucket + FUSE mount | Persistent pipeline state across Cloud Run Job executions |
| Task Queue | Celery + Redis 7 | Background jobs (sync, indexing) |
| LLM (primary) | Anthropic Claude (Sonnet) | Answer generation, entity extraction |
| LLM (alternative) | Google Gemini 2.5 Flash (Vertex AI) | Entity extraction fallback |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Local embedding generation |
| Embeddings (GCP) | Vertex AI text-embedding-005 (768-dim) | Cloud embedding generation |
| Bot | Slack Bolt (HTTP mode) | User interface |
| Web UI | Streamlit | Admin dashboard |
| Graph UI | Neodash | Neo4j graph visualization and dashboards |
| Deployment | Cloud Run (bot, app) + GCE (Neo4j) | Serverless app + stateful graph DB |
| Container | Docker Compose | Local development orchestration |

---

## Deprecated Components

The following components are still referenced in configuration but are no longer active:

| Component | Status | Replacement |
|-----------|--------|-------------|
| ChromaDB | DEPRECATED | Neo4j + Graphiti (episodes with embeddings) |
| DuckDB | NOT IMPLEMENTED | Was planned for analytics, never built |
| NetworkX | REMOVED | Graphiti handles all graph operations |
| Kuzu | DEPRECATED | Was dev-only embedded graph, now Neo4j for all environments |
| BM25 index file | DEPRECATED | Graphiti handles BM25 internally |
| Dual-write mode | DEPRECATED | Migration to Graphiti-only is complete |

---

## Multi-Tenancy

Graphiti supports multi-tenancy via `group_id`. All episodes, entities, and edges are scoped to a group. The default group is configured via `GRAPH_GROUP_ID` (default: `"default"`).

Search operations always filter by `group_ids=[group_id]` to ensure tenant isolation.

---

## Related ADRs

- [ADR-0001](adr/0001-database-duckdb-on-gce.md) - DuckDB for analytics (SUPERSEDED -- never implemented)
- [ADR-0002](adr/0002-vector-store-chromadb-on-cloudrun.md) - ChromaDB as vector store (SUPERSEDED -- replaced by Neo4j + Graphiti)
- [ADR-0003](adr/0003-llm-provider-anthropic-claude.md) - Claude for LLM (ACTIVE)
- [ADR-0004](adr/0004-slack-bot-http-mode-cloudrun.md) - Slack bot deployment (ACTIVE)
- [ADR-0005](adr/0005-chromadb-source-of-truth.md) - ChromaDB as source of truth (SUPERSEDED -- Neo4j + Graphiti is now source of truth)
- [ADR-0010](adr/0010-pipeline-checkpoint-persistence.md) - Pipeline checkpoint persistence via GCS FUSE (ACTIVE)
- [ADR-0006](adr/0006-duckdb-ephemeral-local-storage.md) - DuckDB ephemeral local storage (SUPERSEDED)
- [ADR-0007](adr/0007-github-actions-ci-cd.md) - GitHub Actions CI/CD (ACTIVE)
- [ADR-0008](adr/0008-staging-environment.md) - Staging environment (ACTIVE)

---

## Migration Notes

The system has been fully migrated from ChromaDB to Neo4j + Graphiti. Remaining technical debt:

1. **Config cleanup** - ChromaDB, BM25, Kuzu, and dual-write settings are still present in `config.py` marked as DEPRECATED. These can be removed once all references are cleaned up.
2. **API compatibility shims** - `HybridRetriever` still accepts `bm25_weight` and `vector_weight` parameters for backward compatibility, but they are ignored. Graphiti manages search weighting internally.
3. **Legacy metadata format** - The retriever supports both JSON and pipe-delimited `source_description` formats. The pipe-delimited format is legacy and will be phased out as episodes are re-indexed.
