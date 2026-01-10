# AI Knowledge Base: Master Plan

## Overview

A **self-learning knowledge base** that:
1. Seeds initial content from Confluence Cloud (one-time)
2. Auto-generates metadata (topics, intents, audience) using AI
3. Provides AI-powered semantic search via **Slack** (primary)
4. Continuously learns from user feedback (explicit + implicit)
5. Creates new documents via Slack with AI drafting
6. Enforces approval workflows based on document type

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      USER INTERFACE: SLACK                       │
│  /ask command  │  @bot mentions  │  DM conversations            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       QUERY PLANNING                             │
│  Query Decomposition  │  Source Selection  │  Multi-hop         │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         RETRIEVAL                                │
│  Hybrid Search (BM25+Vector)  │  Graph Traversal  │  Reranking  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        GENERATION                                │
│  RAG Answer  │  Citations  │  LLM-as-Judge Evaluation           │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         LEARNING                                 │
│  Explicit Feedback  │  Behavioral Signals  │  Gap Analysis      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                               │
│  ChromaDB (vectors)  │  SQLite (metadata)  │  NetworkX (graph)  │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| API Framework | FastAPI |
| Primary Interface | Slack Bot (Bolt) |
| Vector Database | ChromaDB (HTTP mode) |
| LLM/Embeddings | Ollama (local) |
| Keyword Search | rank-bm25 |
| Knowledge Graph | NetworkX |
| Metadata Storage | SQLite + SQLAlchemy |
| Task Queue | Celery + Redis |
| Re-ranking | cross-encoder (sentence-transformers) |

## Phase Dependencies

```
Phase 01: Infrastructure
    │
    ▼
Phase 02: Confluence Download
    │
    ▼
Phase 03: Content Parsing
    │
    ├──────────────────────┐
    ▼                      ▼
Phase 04: Metadata    Phase 04.5: Knowledge Graph
    │                      │
    ├──────────────────────┘
    ▼
Phase 05: Vector Indexing ──► Phase 05.5: Hybrid Search (BM25)
    │
    ▼
Phase 06: Search API
    │
    ▼
Phase 07: RAG Answers
    │
    ▼
Phase 08: Slack Bot
    │
    ▼
Phase 09: Permissions
    │
    ▼
Phase 10: Feedback ──► Phase 10.5: Behavioral Signals
    │
    ▼
Phase 11: Quality Scoring ──► Phase 11.5: Nightly Evaluation
    │
    ▼
Phase 12: Governance
    │
    ├──────────────────────┐
    ▼                      ▼
Phase 13: Web UI    Phase 14: Document Creation
(optional)          (Slack-based, AI drafting)
```

## Prerequisites

### Required Credentials

```bash
# Slack
SLACK_BOT_TOKEN=xoxb-xxx
SLACK_APP_TOKEN=xapp-xxx
SLACK_SIGNING_SECRET=xxx

# Confluence
CONFLUENCE_URL=https://keboola.atlassian.net
CONFLUENCE_API_TOKEN=xxx
CONFLUENCE_SPACE_KEYS=ENG,HR,DOCS

# Ollama (pull before Phase 04)
ollama pull mxbai-embed-large
ollama pull llama3.1:8b
```

### Permission Testing (Phase 09)
- Token A: User WITH access to restricted space
- Token B: User WITHOUT access to same space

## Project Structure

```
src/knowledge_base/
├── main.py                 # FastAPI entry point
├── config.py               # Settings
├── slack/                  # Slack Bot
├── api/                    # REST API
├── confluence/             # Confluence client
├── chunking/               # Document parsing
├── metadata/               # AI metadata extraction
├── graph/                  # Knowledge graph
├── vectorstore/            # ChromaDB + embeddings
├── search/                 # Hybrid search (BM25 + vector)
├── rag/                    # RAG pipeline
├── feedback/               # Feedback collection
├── evaluation/             # LLM-as-Judge
├── auth/                   # Authentication
├── db/                     # Database models
└── tasks/                  # Celery tasks
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| BM25 Implementation | rank-bm25 (Python) | Simple, in-memory, <100k docs |
| Knowledge Graph | NetworkX + SQLite | Auto-generated, no Neo4j needed |
| Evaluation | Nightly batch (10%) | Low cost, explicit feedback priority |
| Behavioral Signals | Slack-only | No traditional UI |

## Data Flow: One-Time Sync + Continuous Learning

### 1. Confluence Sync (One-Time + Manual Rebase)
```
Confluence Cloud  ──(initial sync)──►  Knowledge Base
                  ──(manual rebase)──►  (when needed)
```
- **One-time**: Initial download of all content
- **Manual rebase**: CLI command when you want to refresh
- **Staleness flagged**: 2+ year old docs marked as potentially stale

### 2. Continuous Learning (Real-Time)
```
User Interactions (Slack)  ──(real-time)──►  Enrichments
         │                                         │
         ▼                                         ▼
   Feedback/Signals                         Quality Scores
```
- **Real-time**: Captured as users interact
- **Persistent**: Linked by `page_id`, survives rebase
- **Accumulates**: KB gets smarter over time

### Data Preservation on Rebase

| Data Type | Survives Rebase? | Notes |
|-----------|------------------|-------|
| Content/chunks/vectors | Regenerated | Fresh from Confluence |
| **Feedback** | ✅ Yes | Linked by page_id |
| **Quality Scores** | ✅ Yes | Linked by page_id |
| **Behavioral Signals** | ✅ Yes | Linked by page_id |

### The Result

KB becomes **smarter than Confluence** - learns what's useful from user feedback, while stale content (2+ years) is flagged in metadata for governance review.

## How to Use This Plan

1. Check `PROGRESS.md` for current status
2. Find the next pending phase
3. Read the phase folder:
   - `SPEC.md` - What to build
   - `CHECKLIST.md` - Step-by-step tasks
   - `TEST.md` - How to verify
4. Implement, test, mark complete in `PROGRESS.md`

## Quick Reference

- **Full details**: See individual phase folders in `plan/phases/`
- **Architecture decisions**: See `plan/decisions/`
- **Original plan**: See `plan/ARCHIVE_original_plan.md`
