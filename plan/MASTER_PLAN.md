# AI Knowledge Base: Master Plan

## Overview

A **self-learning knowledge base** built on a Neo4j knowledge graph that:
1. Seeds initial content from Confluence Cloud via Keboola batch import (one-time bulk load)
2. Continuously ingests updates via Keboola incremental sync (daily)
3. Accepts user-contributed knowledge via Slack and MCP interfaces
4. Provides AI-powered semantic search with LLM-generated answers
5. Learns from user feedback (explicit ratings + behavioral signals)
6. Enforces risk-based governance for knowledge intake (planned)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INTERFACES                           │
│  Slack Bot (@kb)         │  MCP Server (Claude Desktop)     │
│  @mentions, DMs          │  OAuth 2.1, 6 tools              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      QUERY PIPELINE                          │
│  Query Expansion (LLM)  │  Parallel Search  │  Dedup+Rank   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  RETRIEVAL (Graphiti Hybrid)                  │
│  HNSW Vector Search  │  BM25 Keyword  │  Graph Traversal     │
│  Quality Boost (±20%)  │  Content Filter (min 20 chars)      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      GENERATION                              │
│  RAG Answer (Gemini 2.5 Flash)  │  Source Citations           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       LEARNING                               │
│  Explicit Feedback  │  Quality Scoring  │  Admin Escalation  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      DATA LAYER                              │
│  Neo4j (graph+vectors+BM25)  │  SQLite (metadata+feedback)  │
│  GCS (checkpoints+state)     │  Secret Manager (credentials) │
└─────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Technology | Notes |
|-----------|------------|-------|
| Knowledge Graph | Neo4j 5.26 + Graphiti-core v0.26.3 | Source of truth for all knowledge |
| Vector Search | HNSW indices in Neo4j | 768-dim, O(log N) lookups |
| Keyword Search | BM25 via Graphiti | Hybrid with vector search |
| Metadata DB | SQLite + SQLAlchemy 2.0 async (NullPool) | Page sync, checkpoints, feedback |
| LLM | Gemini 2.5 Flash (Vertex AI) | Entity extraction, answer generation, query expansion |
| Embeddings | Vertex AI text-embedding-005 | 768-dim vectors |
| Bot | Slack Bolt (HTTP mode, Cloud Run) | Primary user interface |
| MCP Server | FastMCP + OAuth 2.1 (Cloud Run) | API for Claude Desktop, other AI agents |
| Infra | Cloud Run + GCE (Neo4j VMs) | Terraform in `deploy/terraform/` |
| CI/CD | GitHub Actions | AI + security review, auto-deploy staging/prod |
| Backup | GCE disk snapshots + nightly staging refresh | 30-day retention, monthly DR test |

## GCP Project

- **Project**: `ai-knowledge-base-42`, region `us-central1`
- **Production Neo4j**: GCE VM `neo4j-prod` (e2-standard-2, 8GB, 50GB pd-ssd)
- **Staging Neo4j**: GCE VM `neo4j-staging` (e2-standard-2, identical to prod)
- **Artifact Registry**: `us-central1-docker.pkg.dev/ai-knowledge-base-42/knowledge-base/`
- **Docker images**: `jobs:latest`, `slack-bot:latest`, `mcp-server:latest` (+ `:staging` tags)

## Knowledge Lifecycle

### 1. Intake

Multiple paths for knowledge to enter the graph:

| Path | Source | Method | Speed |
|------|--------|--------|-------|
| Batch import | Keboola table (pre-chunked Confluence) | Gemini Batch API + Neo4j bulk load | 44K chunks in 4-8h |
| Keboola sync | Keboola incremental (daily Confluence changes) | Graphiti `add_episode()` per chunk | ~1 chunk/min |
| Slack `/create-doc` | User-authored document | AI-assisted drafting + Graphiti indexing | Minutes |
| MCP `create_knowledge` | Quick fact from authenticated user | Direct Graphiti indexing | Seconds |
| Slack `/ingest-doc` | External URL (web/PDF/Google Docs) | Fetch + chunk + Graphiti indexing | Minutes |

### 2. Indexing (Graphiti `add_episode()`)

When a new chunk enters the graph, Graphiti performs 7-20 LLM calls:

```
New chunk arrives
  │
  ▼
Graphiti add_episode()
  ├── Entity Extraction (LLM) — identifies people, teams, tools, concepts
  ├── Entity Deduplication (LLM + embedding similarity)
  │     "Keboola Prague Office" matches existing "Keboola Prague"? → reuse UUID
  ├── Relationship Extraction (LLM) — identifies connections between entities
  ├── Relationship Resolution (LLM) — resolves conflicting relationship facts
  ├── Attribute Extraction (LLM) — adds properties to entities
  └── Episode stored with content, embedding, and metadata JSON
```

**Changes are additive:**
- New entities created only if no existing match
- New edges added to existing entities
- Existing entities and relationships are NOT recalculated
- No cascading changes to the graph

### 3. Search

Hybrid search pipeline:
1. **Query expansion** — LLM generates 3 search variants for better recall
2. **Parallel search** — all variants searched simultaneously via Graphiti
3. **HNSW vector + BM25 keyword** — combined scoring
4. **Episode lookup** — edge results mapped back to source chunks
5. **Content filter** — empty/short results removed (min 20 chars)
6. **Quality boost** — scores adjusted ±20% based on quality metadata
7. **Deduplication** — by episode UUID, keep highest score

### 4. Feedback and Quality Scoring

```
User submits feedback (helpful/outdated/incorrect/confusing)
  │
  ├── Quality score updated in Neo4j episode metadata
  │     helpful: +2, confusing: -5, outdated: -15, incorrect: -25
  │
  ├── Feedback logged to SQLite (analytics + audit)
  │
  ├── Auto-escalation to #knowledge-admins after 3 negative reports in 24h
  │
  └── Admin notified with feedback details + action buttons
```

### 5. Archival

Three-tier system based on quality score:
1. **Deprecated** (score < 40) — excluded from search results, marked for review
2. **Cold storage** (score < 10) — moved to `ArchivedChunk` table, fully removed from search
3. **Hard archive** (90+ days in cold storage) — exported to JSON, deleted from DB

## Data Model

### Neo4j (Graphiti)

**Episodic nodes** (44,484 in production):
- `uuid`, `name`, `content`, `embedding` (768-dim), `group_id`
- `source_description` (JSON): page_id, page_title, space_key, url, author, quality_score, classification, doc_type, chunk_id, chunk_index, owner, feedback_count, access_count

**Entity nodes** (196,131 in production):
- Extracted by LLM from episodes: people, teams, tools, technologies, concepts
- Connected by typed, weighted, temporal relationship edges (400,683 in production)

**HNSW vector indices**:
- `entity_embedding_index` on Entity nodes
- `edge_embedding_index` on Relationship edges

### SQLite (operational metadata)

| Table | Purpose |
|-------|---------|
| `raw_pages` | Confluence page sync tracking |
| `chunk_quality` | Quality score management + archival status |
| `user_feedback` | Explicit feedback records |
| `behavioral_signal` | Implicit signals (thanks, frustration, follow-up) |
| `chunk_access_log` | Usage analytics |
| `bot_response` | Response tracking |
| `documents` | Formal document creation workflow |
| `indexing_checkpoints` | Crash-resilient pipeline checkpoints |

## Phase Overview

```
COMPLETED:
  Phase 1-8:  Core system (Confluence → Neo4j → Search → RAG → Slack Bot)
  Phase 9:    MCP Server (OAuth 2.1, 6 tools, Cloud Run)
  Phase 10:   Feedback (explicit ratings + admin escalation to #knowledge-admins)
  Phase 11:   Quality Scoring (dynamic, usage-based decay, three-tier archival)
  Phase 12:   Batch Import Pipeline (44K chunks via Gemini Batch API, $48, 4-8h)
  Phase 13:   HNSW Vector Indices (O(log N) search, custom SearchInterface)
  Phase 14:   Search Quality (query expansion, content filtering, source rendering)
  Phase 14.5: Feedback UX (button replacement, in-thread confirmation, admin channel)

NEXT:
  Phase 15:   Knowledge Governance (risk-based approval, see ADR-0011)
  Phase 16:   Keboola Incremental Sync (daily updates from Confluence via Keboola)
  Phase 17:   Speed Optimization (parallel search, connection reuse, singleton LLM)

FUTURE:
  Phase 18:   Web UI (optional admin dashboard)
  Phase 19:   Multi-tenant support (multiple knowledge bases per Neo4j instance)
```

## Environments

| Environment | Neo4j | Slack Bot | MCP Server |
|-------------|-------|-----------|------------|
| **Production** | `bolt://10.0.0.27:7687` (internal VPC) | `slack-bot` Cloud Run | `kb-mcp` Cloud Run |
| **Staging** | `bolt+s://neo4j.staging.keboola.dev:443` | `slack-bot-staging` Cloud Run | `kb-mcp-staging` Cloud Run |

- **Always test on staging first** before production
- **Two Slack workspaces**: "Keboola Global" (prod) and "keboola-dev-test" (staging)
- **Two Slack apps**: `knowledgebase` (prod) and `knowledgebasestaging` (staging)

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Knowledge Graph | Neo4j + Graphiti | Rich entity extraction, hybrid search, temporal data |
| LLM Provider | Gemini 2.5 Flash | 65K output tokens (needed for Graphiti), cost-effective |
| Bulk Import | Gemini Batch API | 20x cheaper than Graphiti per-chunk ($48 vs $1000+) |
| Vector Indices | Custom HNSW in Neo4j | Graphiti-core doesn't create indices; brute-force O(N) was too slow |
| SQLite for metadata | NullPool + raw aiosqlite | Avoids WAL lock issues with GCS FUSE |
| Search filtering | Min 20 chars content | Removes empty graph edge facts from results |
| Feedback | Graphiti metadata updates | Neo4j is source of truth; quality_score in episode JSON |
| Governance | Risk-based (planned) | AI classifies risk, auto-approve low risk, hold high risk for admin review |

## Architecture Decisions

See `docs/adr/` for detailed ADRs:
- ADR-0009: Neo4j + Graphiti as knowledge store (supersedes ChromaDB)
- ADR-0010: Pipeline checkpoint persistence via GCS FUSE
- ADR-0011: Knowledge governance — risk-based approval (planned)
