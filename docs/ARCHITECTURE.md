# Architecture Principles

This document defines the canonical architecture principles for the AI Knowledge Base system. All implementation decisions should align with these principles.

**Last Updated:** 2026-01-03

---

## Core Principles

### Principle 1: ChromaDB is the Source of Truth for Knowledge

ChromaDB is the **primary and authoritative store** for all knowledge-related data. This includes:

- **Document chunks** - The actual content being searched
- **Vector embeddings** - For semantic similarity search
- **ALL metadata** - No separate metadata store needed

**Metadata stored in ChromaDB per chunk:**

| Field | Type | Description |
|-------|------|-------------|
| `page_id` | string | Unique identifier for the source page |
| `page_title` | string | Human-readable title |
| `space_key` | string | Confluence space or source category |
| `url` | string | Link to original document |
| `author` | string | Content author (name or ID) |
| `created_at` | ISO datetime | When content was created |
| `updated_at` | ISO datetime | Last modification time |
| `chunk_type` | string | text, code, table, list |
| `chunk_index` | integer | Position within the page |
| `quality_score` | float | 0-100, updated directly in ChromaDB |
| `owner` | string | Content owner (governance) |
| `reviewed_by` | string | Last reviewer |
| `reviewed_at` | ISO datetime | Last review date |
| `classification` | string | public, internal, confidential |
| `doc_type` | string | policy, how-to, reference, FAQ |
| `topics` | JSON string | Array of topic tags |
| `audience` | JSON string | Target audience types |
| `complexity` | string | beginner, intermediate, advanced |
| `summary` | string | AI-generated summary (1-2 sentences) |

---

### Principle 2: DuckDB is for Analytics & Retraining Only

DuckDB stores **only** data needed for:
1. **Future model retraining** - User corrections and feedback
2. **Usage analytics** - Behavioral patterns and satisfaction metrics

**DuckDB Tables (Minimal):**

| Table | Purpose |
|-------|---------|
| `user_feedback` | Explicit feedback (helpful, incorrect, outdated, confusing) with comments and suggested corrections |
| `behavioral_signal` | Implicit signals (thanks, frustration, reactions) for analytics |

**DuckDB does NOT store:**
- Document content or chunks
- Quality scores (these live in ChromaDB)
- Governance metadata
- Page metadata

---

### Principle 3: No Duplication of Source of Truth

Each piece of data lives in **exactly one place**:

| Data Type | Location | Rationale |
|-----------|----------|-----------|
| Chunk content | ChromaDB | Primary search store |
| Vector embeddings | ChromaDB | Semantic search |
| Quality scores | ChromaDB metadata | Filter/boost during search |
| Governance info | ChromaDB metadata | Filter during search |
| User feedback | DuckDB | Retraining data (future use) |
| Behavioral signals | DuckDB | Analytics data |

**Why no duplication?**
- Eliminates sync complexity
- Single source of truth prevents inconsistencies
- Simpler mental model for developers
- Faster operations (no cross-database updates)

---

### Principle 4: Quality Scores are ChromaDB-Native

Quality scores are managed **entirely within ChromaDB**:

```
1. New chunk created
   └─► quality_score: 100.0 in ChromaDB metadata

2. User gives feedback
   └─► Update ChromaDB metadata directly
   └─► Log to DuckDB (for retraining, async)

3. Search query
   └─► ChromaDB filters/boosts by quality_score
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
┌─────────────────────────────────────────────────────────────────┐
│                         SLACK BOT                                │
│                      (Cloud Run - HTTP)                          │
└─────────────────────────────────────────────────────────────────┘
                    │                          │
                    │ Questions/               │ Feedback/
                    │ Knowledge Creation       │ Reactions
                    ▼                          ▼
┌─────────────────────────────────┐  ┌─────────────────────────────┐
│         CHROMADB                │  │         DUCKDB              │
│    (Source of Truth)            │  │    (Analytics Only)         │
├─────────────────────────────────┤  ├─────────────────────────────┤
│                                 │  │                             │
│  Collection: knowledge_chunks   │  │  Tables:                    │
│                                 │  │  - user_feedback            │
│  Per chunk:                     │  │  - behavioral_signal        │
│  - id: chunk_id                 │  │                             │
│  - embedding: vector[768]       │  │  Purpose:                   │
│  - document: content            │  │  - Retraining data          │
│  - metadata: (see table above)  │  │  - Usage analytics          │
│                                 │  │  - Pattern detection        │
│  Quality scores: NATIVE         │  │                             │
│  Governance: NATIVE             │  │  Links to ChromaDB via      │
│                                 │  │  chunk_id reference         │
└─────────────────────────────────┘  └─────────────────────────────┘
```

---

## Data Flows

### Flow 1: Content Ingestion (Confluence Sync)

```
Confluence API
    │
    ▼
Parse & Chunk
    │
    ▼
Generate Embeddings (Vertex AI)
    │
    ▼
ChromaDB.upsert(
    ids=[chunk_id],
    embeddings=[vector],
    documents=[content],
    metadatas=[{
        page_id, page_title, space_key, url,
        author, updated_at, chunk_type,
        quality_score: 100.0,  # Default
        owner, classification, doc_type, topics, ...
    }]
)
```

### Flow 2: Question Answering

```
User Question
    │
    ▼
ChromaDB.query(
    query_embedding=embed(question),
    n_results=10,
    where={"quality_score": {"$gte": 50}}  # Filter low quality
)
    │
    ▼
Rank by: similarity * quality_boost
    │
    ▼
LLM generates answer from top chunks
    │
    ▼
Return answer + feedback buttons
```

### Flow 3: Feedback Processing

```
User clicks "Incorrect"
    │
    ├─────────────────────────────────┐
    │                                 │
    ▼                                 ▼
ChromaDB.update(                  DuckDB.insert(
    ids=[chunk_id],                   user_feedback(
    metadatas=[{                          chunk_id,
        quality_score: old - 25           feedback_type="incorrect",
    }]                                    comment,
)                                         suggested_correction,
                                          user_id, timestamp
                                      )
                                  )
    │
    ▼
Notify content owner (if applicable)
```

### Flow 4: Behavioral Signal Capture

```
User says "thanks" in thread
    │
    ▼
DuckDB.insert(
    behavioral_signal(
        chunk_ids=[...],
        signal_type="thanks",
        signal_value=0.4,
        user_id, timestamp
    )
)
```

**Note:** Behavioral signals go to DuckDB only (analytics). They do NOT update ChromaDB quality scores - only explicit feedback does.

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Vector Store | ChromaDB on Cloud Run | Knowledge storage + search |
| Analytics DB | DuckDB on GCE | Feedback + signals storage |
| Embeddings | Vertex AI text-embedding-005 | 768-dim vectors |
| LLM | Claude (Anthropic API) | Answer generation |
| Bot | Slack Bolt (HTTP mode) | User interface |
| Deployment | Cloud Run + GCE | Serverless + stateful |

---

## Related ADRs

- [ADR-0001](adr/0001-database-duckdb-on-gce.md) - DuckDB for analytics only
- [ADR-0002](adr/0002-vector-store-chromadb-on-cloudrun.md) - ChromaDB as vector store
- [ADR-0003](adr/0003-llm-provider-anthropic-claude.md) - Claude for LLM
- [ADR-0004](adr/0004-slack-bot-http-mode-cloudrun.md) - Slack bot deployment
- [ADR-0005](adr/0005-chromadb-source-of-truth.md) - ChromaDB as source of truth

---

## Migration Notes

The current implementation has technical debt from an earlier architecture where SQLite stored duplicate data. Future work should:

1. Remove unused SQLAlchemy models (keep only UserFeedback, BehavioralSignal)
2. Update ingestion to write all metadata to ChromaDB
3. Update feedback handlers to write quality directly to ChromaDB
4. Migrate feedback tables from SQLite to DuckDB
