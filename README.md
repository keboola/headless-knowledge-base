# AI Knowledge Base

A self-learning, AI-powered knowledge base that provides semantic search and RAG (Retrieval-Augmented Generation) capabilities via Slack.

## Project Overview

This system:
1. Seeds content from Confluence Cloud (one-time sync with manual rebase)
2. Auto-generates metadata (topics, intents, audience) using AI
3. Provides AI-powered semantic search via **Slack** (primary interface)
4. Continuously learns from user feedback (explicit + implicit signals)
5. Creates new documents via Slack with AI drafting
6. Enforces approval workflows based on document type

**Status**: All 18 phases completed and functional.

---

## Architecture

```
                           USER INTERFACE: SLACK
           /ask command  |  @bot mentions  |  DM conversations
                                 |
                                 v
                          QUERY PLANNING
          Query Decomposition  |  Source Selection  |  Multi-hop
                                 |
                                 v
                            RETRIEVAL
         Hybrid Search (BM25+Vector)  |  Graph Traversal  |  Reranking
                                 |
                                 v
                           GENERATION
              RAG Answer  |  Citations  |  LLM-as-Judge Evaluation
                                 |
                                 v
                            LEARNING
          Explicit Feedback  |  Behavioral Signals  |  Gap Analysis
                                 |
                                 v
                           DATA LAYER
      Neo4j + Graphiti (knowledge graph)  |  SQLite (metadata)  |  Redis (queue)
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Language** | Python 3.11+ |
| **API Framework** | FastAPI |
| **Primary Interface** | Slack Bot (Bolt) |
| **Knowledge Graph** | Neo4j 5.26 + Graphiti-core (temporal knowledge graph) |
| **Graph Protocol** | Bolt (port 7687) |
| **LLM Provider** | Anthropic Claude (primary), Gemini (alternative via Vertex AI) |
| **Embeddings** | sentence-transformers / Vertex AI |
| **Metadata Storage** | SQLite + SQLAlchemy 2.0 (async) |
| **Task Queue** | Celery + Redis |
| **Web UI** | Streamlit, Neodash (Neo4j dashboards) |

---

## Project Structure

```
ai-based-knowledge/
├── src/knowledge_base/          # Main application code
│   ├── api/                     # REST API endpoints
│   ├── auth/                    # Authentication & authorization
│   ├── chunking/                # Document parsing & chunking
│   ├── cli.py                   # CLI commands (kb command)
│   ├── config.py                # Application settings
│   ├── confluence/              # Confluence sync client
│   ├── db/                      # Database models (SQLAlchemy)
│   ├── documents/               # Document creation & approval
│   ├── evaluation/              # LLM-as-Judge quality scoring
│   ├── governance/              # Gap analysis, obsolete detection
│   ├── graph/                   # Knowledge graph (Graphiti + Neo4j)
│   ├── lifecycle/               # Document lifecycle management
│   ├── main.py                  # FastAPI entry point
│   ├── metadata/                # AI metadata extraction
│   ├── rag/                     # RAG pipeline & LLM providers
│   ├── search/                  # Search integration (Graphiti-powered)
│   ├── slack/                   # Slack bot integration
│   ├── vectorstore/             # Embeddings (legacy, deprecated)
│   └── web/                     # Streamlit web UI
├── tests/                       # Test suite
├── plan/                        # Implementation planning docs
│   ├── MASTER_PLAN.md          # High-level architecture & phases
│   ├── PROGRESS.md             # Implementation progress tracker
│   └── phases/                  # Detailed specs per phase
├── docs/                        # Documentation
│   ├── adr/                     # Architecture Decision Records
│   └── AGENT-REPORTS/           # Security & analysis reports
├── deploy/                      # Deployment configurations
├── docker-compose.yml           # Local development setup
├── Dockerfile                   # Container build
└── pyproject.toml              # Python dependencies
```

---

## Key Features

### 1. Confluence Sync
- One-time initial sync from Confluence Cloud
- Manual rebase via CLI when refresh needed
- Preserves user feedback and quality scores across rebases

### 2. Hybrid Search (Graphiti-powered)
- **Semantic search** via Graphiti embeddings
- **Graph traversal** via Neo4j for related content and multi-hop queries
- **Temporal awareness** via Graphiti's bi-temporal model
- **Entity-based retrieval** for precise knowledge graph queries

### 3. RAG Pipeline
- Retrieves relevant chunks from hybrid search
- Generates answers using LLM (Claude/Gemini)
- Includes source citations in responses

### 4. Feedback & Learning
- **Explicit feedback**: Thumbs up/down buttons in Slack
- **Behavioral signals**: Reactions, gratitude, frustration detection
- **Quality scoring**: Normalized scores boost search ranking

### 5. Governance
- Gap analysis for unanswered questions
- Obsolete content detection (2+ years old)
- Nightly LLM-as-Judge evaluation

### 6. Document Creation
- Create documents via Slack (`/create-doc` or "Save as Doc")
- AI drafting assistance
- Approval workflows

---

## Quick Start

### Prerequisites
```bash
# Required environment variables
SLACK_BOT_TOKEN=xoxb-xxx
SLACK_APP_TOKEN=xapp-xxx
SLACK_SIGNING_SECRET=xxx
CONFLUENCE_URL=https://your-org.atlassian.net
CONFLUENCE_API_TOKEN=xxx
CONFLUENCE_SPACE_KEYS=DOCS,ENG
ANTHROPIC_API_KEY=sk-ant-xxx
```

### Installation
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .

# Run locally with Docker Compose
docker-compose up -d
```

### CLI Commands
```bash
# Sync from Confluence
kb sync --space DOCS

# Run search
kb search "how to deploy"

# Generate metadata for all pages
kb metadata generate

# Build knowledge graph
kb graph build

# Start Slack bot
kb slack start
```

---

## Data Flow

### Initial Sync
```
Confluence Cloud  --(initial sync)-->  Knowledge Base
                  --(manual rebase)-->  (when needed)
```

### Continuous Learning
```
User Interactions (Slack)  --(real-time)-->  Enrichments
         |                                         |
         v                                         v
   Feedback/Signals                         Quality Scores
```

### Data Preservation on Rebase
| Data Type | Survives Rebase? | Notes |
|-----------|------------------|-------|
| Content/chunks/vectors | Regenerated | Fresh from Confluence |
| **Feedback** | Yes | Linked by page_id |
| **Quality Scores** | Yes | Linked by page_id |
| **Behavioral Signals** | Yes | Linked by page_id |

---

## Architecture Decisions

Key decisions documented in `docs/adr/`:

| ADR | Decision | Status |
|-----|----------|--------|
| ADR-0001 | DuckDB on GCE | Accepted |
| ADR-0002 | ChromaDB on Cloud Run | Superseded by ADR-0009 |
| ADR-0003 | Anthropic Claude | Accepted |
| ADR-0004 | Slack Bot HTTP Mode | Accepted |
| ADR-0005 | ChromaDB as Source of Truth | Superseded by ADR-0009 |
| ADR-0009 | Neo4j + Graphiti as Knowledge Store | Accepted |

---

## Implementation Phases

All 18 phases completed:

| Phase | Name | Status |
|-------|------|--------|
| 01 | Infrastructure | Done |
| 02 | Confluence Download | Done |
| 03 | Content Parsing | Done |
| 04 | Metadata Generation | Done |
| 04.5 | Knowledge Graph | Done |
| 05 | Vector Indexing | Done |
| 05.5 | Hybrid Search | Done |
| 06 | Search API | Done |
| 07 | RAG Answers | Done |
| 08 | Slack Bot | Done |
| 09 | Permissions | Done |
| 10 | Feedback Collection | Done |
| 10.5 | Behavioral Signals | Done |
| 11 | Quality Scoring | Done |
| 11.5 | Nightly Evaluation | Done |
| 12 | Governance | Done |
| 13 | Web UI | Done |
| 14 | Document Creation | Done |

See `plan/PROGRESS.md` for detailed changelog.

---

## For AI Agents

### Repository Navigation

**To understand this project:**
1. Start with `plan/MASTER_PLAN.md` for high-level architecture
2. Check `plan/PROGRESS.md` for implementation status
3. Browse `plan/phases/` for detailed specs of each component
4. See `docs/adr/` for architectural decisions

**Key source directories:**
- `src/knowledge_base/rag/` - RAG pipeline and LLM providers
- `src/knowledge_base/search/` - Hybrid search implementation
- `src/knowledge_base/slack/` - Slack bot integration
- `src/knowledge_base/vectorstore/` - Embeddings (legacy, deprecated)
- `src/knowledge_base/graph/` - Knowledge graph (Graphiti + Neo4j)

**Configuration:**
- `src/knowledge_base/config.py` - All settings with env var overrides
- `.env.example` - Environment variable template
- `docker-compose.yml` - Local development services

**Tests:**
- `tests/` - Pytest-based test suite
- Run with: `pytest tests/`

### Code Patterns

This codebase uses:
- **Async/await** for all I/O operations
- **Pydantic** for data validation and settings
- **SQLAlchemy 2.0** async patterns for database
- **Dependency injection** via FastAPI
- **Structured logging** throughout
- **Type hints** everywhere (mypy strict mode)

### Common Tasks

**Adding a new LLM provider:**
1. Create provider in `src/knowledge_base/rag/providers/`
2. Implement `BaseLLMProvider` interface
3. Register in `src/knowledge_base/rag/llm_factory.py`

**Adding a new search source:**
1. Implement retriever in `src/knowledge_base/search/`
2. Add to hybrid search fusion in `hybrid.py`

**Modifying Slack commands:**
1. Edit `src/knowledge_base/slack/bot.py`
2. Add command handlers following existing patterns

---

## Security

See `docs/AGENT-REPORTS/SECURITY.md` for full security review.

**Key considerations:**
- All secrets via environment variables
- Slack signing secret verification
- Permission checks on all queries
- No hardcoded credentials

---

## License

GPL-3.0-or-later - See [LICENSE](LICENSE)
