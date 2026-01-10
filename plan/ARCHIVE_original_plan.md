# Knowledge Base System: Self-Learning Confluence + RAG

## Overview

A **self-learning knowledge base** that:
1. Downloads documents from Confluence Cloud
2. **Auto-generates metadata** (topics, intents, audience, doc type) using AI
3. Provides AI-powered semantic search via **Slack (primary)** and web UI (secondary)
4. **Continuously learns** from user feedback (explicit + implicit)
5. **Daily re-evaluates** metadata and quality scores
6. Enforces Confluence permissions at query time
7. Enables **governance** - identifies obsolete content for policy agents

## Tech Stack

| Component | Technology |
|-----------|------------|
| API Framework | FastAPI |
| **Primary Interface** | **Slack Bot (Bolt)** |
| Secondary Interface | Web UI (HTML/CSS/JS) |
| Vector Database | ChromaDB (HTTP mode) |
| LLM/Embeddings | Ollama (local) |
| Metadata Storage | SQLite + SQLAlchemy |
| Confluence API | atlassian-python-api |
| Task Queue | Celery + Redis |
| Re-ranking | cross-encoder (sentence-transformers) |
| Authentication | Slack OAuth + Google OAuth (web) |
| Deployment | Docker Compose |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INTERFACES                          │
├─────────────────────────────────────────────────────────────────┤
│  SLACK (Primary)              │  WEB UI (Secondary)             │
│  - /ask command               │  - Search interface              │
│  - @bot mentions              │  - Admin dashboard               │
│  - DM conversations           │  - Governance reports            │
│  - Inline feedback buttons    │  - Confluence linking            │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                         CORE SERVICES                            │
├─────────────────────────────────────────────────────────────────┤
│  FastAPI Backend                                                 │
│  ├── RAG Pipeline (search → permission check → rerank → LLM)   │
│  ├── Feedback Collection (explicit + implicit + conversation)   │
│  └── Metadata Service (auto-generation + daily refresh)         │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                               │
├─────────────────────────────────────────────────────────────────┤
│  ChromaDB (vectors + metadata)  │  SQLite (feedback, sessions)  │
│  - Document embeddings          │  - User interactions           │
│  - Auto-generated metadata      │  - Feedback scores             │
│  - Quality scores               │  - Conversation history        │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BACKGROUND WORKERS                          │
├─────────────────────────────────────────────────────────────────┤
│  Celery Tasks                                                    │
│  ├── Confluence Sync (two-way reconciliation)                   │
│  ├── Metadata Generation (AI-powered)                           │
│  ├── Daily Re-evaluation (metadata + quality scores)            │
│  └── Feedback Aggregation (learn from signals)                  │
└─────────────────────────────────────────────────────────────────┘
```

## Automatic Metadata Generation

### Per-Document Metadata (AI-Generated)

| Field | Description | Example |
|-------|-------------|---------|
| **topics** | What is this doc about? | ["onboarding", "benefits", "PTO"] |
| **intents** | What situations is this useful for? | ["new_employee", "planning_vacation"] |
| **audience** | Who should read this? | ["all_employees", "engineering"] |
| **doc_type** | What kind of document? | "policy", "how-to", "reference", "FAQ" |
| **key_entities** | Products, services, locations | ["GCP", "Snowflake", "Prague office"] |
| **summary** | 1-2 sentence summary | "Describes PTO policy and how to request time off" |
| **complexity** | Reading level | "beginner", "intermediate", "advanced" |
| **freshness_status** | Based on last update | "fresh", "aging", "obsolete" |
| **quality_score** | Based on user feedback | 0.0 - 1.0 |
| **relevance_score** | How often is this doc useful? | 0.0 - 1.0 |

### Metadata Generation Process

```
New/Updated Document
        │
        ▼
┌───────────────────────────────────┐
│  LLM Metadata Extraction          │
│  Prompt:                          │
│  "Analyze this document and       │
│   extract:                        │
│   - Main topics (3-5)             │
│   - Use case intents (2-3)        │
│   - Target audience               │
│   - Document type                 │
│   - Key entities mentioned        │
│   - Brief summary"                │
└───────────────────────────────────┘
        │
        ▼
    Store in ChromaDB metadata
        │
        ▼
    Daily Re-evaluation Job
    (adjust based on feedback)
```

### Daily Re-evaluation Job

Runs every night to:
1. **Recalculate quality scores** based on accumulated feedback
2. **Update relevance scores** based on how often docs appear in useful answers
3. **Re-cluster topics** if new patterns emerge
4. **Flag obsolete content** for governance (old + low engagement + negative feedback)
5. **Identify gaps** - common questions with no good answers

## User Feedback System

### Feedback Types

| Type | Signal | Weight | Example |
|------|--------|--------|---------|
| **Explicit Positive** | Thumbs up | 1.0 | User clicks 👍 |
| **Explicit Negative** | Thumbs down | -1.0 | User clicks 👎 |
| **Follow-up Question** | User asks again | -0.3 | "That's not what I meant..." |
| **Link Click** | User opens source | +0.2 | Clicked Confluence link |
| **Conversation End** | No follow-up | +0.1 | User satisfied, conversation ends |
| **Suggestion Provided** | User gives feedback | varies | "You should also mention X" |

### Feedback Collection in Slack

```
User: /ask How do I request PTO?

Bot: Based on our knowledge base, here's how to request PTO:

1. Go to Workday portal
2. Select "Time Off" → "Request"
3. Choose dates and submit

📄 Sources:
- [PTO Policy](https://confluence.../pto-policy) (last updated: 2 months ago)
- [Workday Guide](https://confluence.../workday) (last updated: 1 week ago)

Was this helpful?  [👍 Yes]  [👎 No]  [💡 Suggest improvement]
```

### Feedback Data Model

```python
class Feedback(Base):
    id: int
    user_id: str  # Slack user ID
    query: str  # Original question
    response_id: str  # Response tracking ID
    documents_shown: List[str]  # page_ids included in answer
    feedback_type: str  # "thumbs_up", "thumbs_down", "suggestion", "follow_up", etc.
    feedback_value: float  # Normalized score
    suggestion_text: Optional[str]  # If user provided text
    created_at: datetime
```

## Slack Bot Integration

### Interaction Modes

1. **Slash Command**: `/ask <question>`
2. **Mention**: `@knowledge-bot <question>`
3. **DM**: Direct message to bot

### Bot Features

- **Threaded Responses**: Answers in thread to keep channels clean
- **Source Citations**: Links to Confluence pages
- **Freshness Warnings**: Warn if sources are old
- **Feedback Buttons**: Inline 👍/👎 buttons
- **Follow-up Support**: Remember conversation context
- **Permission Check**: Uses user's Confluence access (via linked account)

### Slack → Confluence Linking

Users must link their Confluence account to enable permission-based search:

```
User: /ask How do I deploy to production?

Bot: ⚠️ To search the knowledge base, please link your Confluence account first.
     [🔗 Link Confluence Account]

(After linking)

User: /ask How do I deploy to production?

Bot: Here's the deployment process...
```

## Project Structure

```
ai-based-knowledge/
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── .env.example
│
├── src/
│   └── knowledge_base/
│       ├── __init__.py
│       ├── main.py                   # FastAPI entry point
│       ├── config.py                 # Settings
│       │
│       ├── slack/                    # Slack Bot (PRIMARY)
│       │   ├── __init__.py
│       │   ├── app.py                # Bolt app setup
│       │   ├── commands.py           # /ask command handler
│       │   ├── events.py             # Mention, DM handlers
│       │   ├── interactions.py       # Button clicks, feedback
│       │   ├── messages.py           # Message formatting
│       │   └── auth.py               # Slack OAuth, user linking
│       │
│       ├── api/                      # REST API
│       │   ├── search.py
│       │   ├── documents.py
│       │   ├── feedback.py           # Feedback submission
│       │   ├── governance.py         # Obsolete docs, gaps
│       │   ├── sync.py
│       │   └── health.py
│       │
│       ├── metadata/                 # Auto Metadata Generation
│       │   ├── __init__.py
│       │   ├── extractor.py          # LLM-based extraction
│       │   ├── schemas.py            # Metadata schemas
│       │   ├── evaluator.py          # Daily re-evaluation
│       │   └── clustering.py         # Topic clustering
│       │
│       ├── feedback/                 # Feedback & Learning
│       │   ├── __init__.py
│       │   ├── collector.py          # Collect all signals
│       │   ├── analyzer.py           # Analyze patterns
│       │   ├── scorer.py             # Update quality scores
│       │   └── models.py             # Feedback data models
│       │
│       ├── confluence/
│       │   ├── client.py
│       │   ├── parser.py
│       │   ├── permissions.py
│       │   └── sync.py
│       │
│       ├── vectorstore/
│       │   ├── client.py
│       │   ├── embeddings.py
│       │   ├── indexer.py
│       │   └── retriever.py
│       │
│       ├── rag/
│       │   ├── chain.py
│       │   ├── prompts.py
│       │   ├── reranker.py
│       │   └── llm.py
│       │
│       ├── chunking/
│       │   ├── html_chunker.py
│       │   ├── table_handler.py
│       │   └── strategies.py
│       │
│       ├── auth/
│       │   ├── slack_oauth.py        # Slack workspace auth
│       │   ├── confluence_link.py    # User Confluence linking
│       │   └── google.py             # Web UI auth
│       │
│       ├── db/
│       │   ├── database.py
│       │   ├── models.py
│       │   └── repository.py
│       │
│       └── tasks/
│           ├── celery_app.py
│           ├── sync_tasks.py
│           ├── metadata_tasks.py     # Metadata generation
│           ├── feedback_tasks.py     # Feedback aggregation
│           └── evaluation_tasks.py   # Daily re-evaluation
│
├── frontend/                         # Web UI (secondary)
│
└── tests/
```

## Data Models

### ChromaDB Metadata (Extended)

| Field | Type | Description |
|-------|------|-------------|
| page_id | string | Confluence page ID |
| page_title | string | Page title |
| space_key | string | Space key |
| author | string | Last modifier |
| url | string | Confluence URL |
| updated_at | ISO string | Last update |
| **topics** | string (JSON) | Auto-extracted topics |
| **intents** | string (JSON) | Use case intents |
| **audience** | string (JSON) | Target audience |
| **doc_type** | string | Document type |
| **key_entities** | string (JSON) | Products, services mentioned |
| **summary** | string | Brief summary |
| **freshness_status** | string | fresh/aging/obsolete |
| **quality_score** | float | 0.0-1.0 based on feedback |
| **relevance_score** | float | 0.0-1.0 based on usage |

### SQLite Tables (Extended)

**feedback** - User feedback on responses
- id, user_id, query, response_id
- documents_shown (JSON), feedback_type, feedback_value
- suggestion_text, created_at

**conversations** - Conversation history
- id, user_id, channel_id, thread_ts
- messages (JSON), started_at, ended_at
- satisfaction_score (computed)

**governance_issues** - Flagged content
- id, page_id, issue_type (obsolete, low_quality, missing_info)
- detected_at, resolved_at, assigned_to

**user_confluence_links** - User account linking
- user_id (Slack), confluence_token (encrypted)
- linked_at, last_used_at

## API Endpoints (Extended)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/search` | Semantic search with RAG |
| POST | `/api/v1/feedback` | Submit feedback |
| GET | `/api/v1/feedback/stats` | Feedback statistics |
| GET | `/api/v1/governance/obsolete` | List obsolete docs |
| GET | `/api/v1/governance/gaps` | Unanswered questions |
| GET | `/api/v1/governance/low-quality` | Low quality docs |
| POST | `/api/v1/metadata/regenerate` | Force metadata regeneration |
| GET | `/api/v1/metadata/topics` | List discovered topics |
| POST | `/slack/events` | Slack event webhook |
| POST | `/slack/interactions` | Slack button clicks |
| POST | `/slack/commands` | Slack slash commands |

## Docker Services (Extended)

```yaml
services:
  knowledge-base:    # FastAPI + Slack bot (port 8000)
  celery-worker:     # Background tasks
  celery-beat:       # Scheduled tasks (daily evaluation)
  redis:             # Message broker
  chromadb:          # Vector DB (port 8001)
  ollama:            # LLM server (port 11434)
  ollama-init:       # Model pull
  frontend:          # Web UI (port 3000)
```

## Implementation Phases (Testable & Idempotent)

Each phase is independently testable with clear inputs/outputs. All operations are idempotent.

---

### Phase 1: Infrastructure
**Goal:** All services running, health checks pass

**Deliverables:**
- `pyproject.toml` with dependencies
- `docker-compose.yml` with all services
- `Dockerfile` for the app
- `.env.example` with config vars
- FastAPI app with `/health` endpoint

**Test:**
```bash
docker-compose up -d
curl http://localhost:8000/health  # Returns {"status": "ok"}
```

**Idempotent:** Yes - restart services anytime

---

### Phase 2: Confluence Download
**Goal:** Download all pages from configured Confluence spaces to local storage

**Input:** Confluence credentials + space keys
**Output:** Raw pages stored in SQLite (page_id, html_content, metadata)

**Deliverables:**
- `confluence/client.py` - API client with rate limiting
- `confluence/downloader.py` - Page fetcher
- `db/models.py` - RawPage model
- CLI command: `kb-download --spaces=SPACE1,SPACE2`

**Test:**
```bash
python -m knowledge_base.cli download --spaces=ENG,HR
# Check: SELECT COUNT(*) FROM raw_pages; → returns page count
```

**Idempotent:** Yes - re-download updates existing, adds new, marks deleted

---

### Phase 3: Content Parsing
**Goal:** Parse raw HTML into clean text chunks

**Input:** Raw pages from Phase 2
**Output:** Parsed chunks stored in SQLite (chunk_id, page_id, content, chunk_type)

**Deliverables:**
- `chunking/html_chunker.py` - HTML → text
- `chunking/table_handler.py` - Table preservation
- `chunking/macro_handler.py` - Confluence macros
- `attachments/pdf.py`, `attachments/docx.py` - Attachment parsing
- CLI command: `kb-parse`

**Test:**
```bash
python -m knowledge_base.cli parse
# Check: SELECT COUNT(*) FROM chunks; → returns chunk count
# Verify: Tables kept intact, code blocks preserved
```

**Idempotent:** Yes - re-parse regenerates all chunks for changed pages

---

### Phase 4: Metadata Generation
**Goal:** Auto-generate metadata for each chunk using LLM

**Input:** Parsed chunks from Phase 3
**Output:** Metadata attached to chunks (topics, intents, audience, doc_type, summary)

**Deliverables:**
- `metadata/extractor.py` - LLM-based extraction
- `metadata/normalizer.py` - Vocabulary normalization
- `metadata/schemas.py` - Metadata Pydantic models
- CLI command: `kb-metadata`

**Test:**
```bash
python -m knowledge_base.cli metadata
# Check: SELECT topics, intents FROM chunk_metadata LIMIT 5;
# Verify: Valid JSON arrays, normalized vocabulary
```

**Idempotent:** Yes - re-run regenerates metadata for all/changed chunks

---

### Phase 5: Vector Indexing
**Goal:** Create embeddings and store in ChromaDB

**Input:** Chunks with metadata from Phase 4
**Output:** Documents indexed in ChromaDB collection

**Deliverables:**
- `vectorstore/embeddings.py` - Ollama embeddings (abstract interface)
- `vectorstore/indexer.py` - ChromaDB indexer
- `vectorstore/client.py` - ChromaDB client (abstract interface)
- CLI command: `kb-index`

**Test:**
```bash
python -m knowledge_base.cli index
# Check: ChromaDB collection count matches chunk count
curl http://localhost:8001/api/v1/collections/confluence_documents
```

**Idempotent:** Yes - re-index upserts (update or insert)

---

### Phase 6: Search API
**Goal:** Vector search endpoint (no auth yet)

**Input:** User query string
**Output:** Ranked list of relevant chunks with metadata

**Deliverables:**
- `vectorstore/retriever.py` - Search logic
- `rag/reranker.py` - Cross-encoder re-ranking
- `api/search.py` - Search endpoint

**Test:**
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I request PTO?"}'
# Returns: List of relevant documents with scores
```

**Idempotent:** Yes - search is read-only

---

### Phase 7: RAG Answer Generation
**Goal:** Generate natural language answers using LLM

**Input:** Query + retrieved chunks
**Output:** Answer with source citations

**Deliverables:**
- `rag/llm.py` - Ollama LLM wrapper (abstract interface)
- `rag/chain.py` - RAG orchestration
- `rag/prompts.py` - Prompt templates
- Updated search endpoint with `include_answer=true`

**Test:**
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -d '{"query": "How do I request PTO?", "include_answer": true}'
# Returns: {"answer": "...", "sources": [...]}
```

**Idempotent:** Yes - same query produces similar answers

---

### Phase 8: Slack Bot
**Goal:** Basic /ask command in Slack

**Input:** Slack message
**Output:** Formatted answer in Slack thread

**Deliverables:**
- `slack/app.py` - Bolt app setup
- `slack/commands.py` - /ask handler
- `slack/messages.py` - Message formatting
- Slack app manifest

**Test:**
```
In Slack: /ask How do I request PTO?
Bot replies with answer + sources in thread
```

**Idempotent:** Yes - same question produces same answer format

---

### Phase 9: Permission Checking
**Goal:** Filter results based on user's Confluence permissions

**Input:** User's Confluence token + search results
**Output:** Filtered results (only authorized docs)

**Deliverables:**
- `auth/confluence_link.py` - Account linking flow
- `confluence/permissions.py` - Permission checker
- `auth/cache.py` - Permission caching (Redis)
- Updated Slack flow with linking prompt

**Test:**
```bash
# User A (has access to HR space) searches → sees HR docs
# User B (no HR access) searches → doesn't see HR docs
```

**Idempotent:** Yes - same user sees same filtered results

---

### Phase 10: Feedback Collection
**Goal:** Collect thumbs up/down from Slack

**Input:** User clicks feedback button
**Output:** Feedback stored in SQLite

**Deliverables:**
- `slack/interactions.py` - Button click handler
- `feedback/collector.py` - Store feedback
- `feedback/models.py` - Feedback data model
- Updated Slack messages with feedback buttons

**Test:**
```
In Slack: Click 👍 on bot response
Check: SELECT * FROM feedback WHERE response_id = 'xxx';
```

**Idempotent:** Yes - clicking again updates existing feedback

---

### Phase 11: Quality Scoring
**Goal:** Daily job to update document quality scores

**Input:** Accumulated feedback
**Output:** Updated quality_score in ChromaDB metadata

**Deliverables:**
- `feedback/scorer.py` - Score calculation
- `tasks/evaluation_tasks.py` - Celery task
- Celery Beat schedule for daily run

**Test:**
```bash
python -m knowledge_base.cli evaluate
# Check: Documents with positive feedback have higher quality_score
```

**Idempotent:** Yes - re-run recalculates all scores from scratch

---

### Phase 12: Governance Reports
**Goal:** Identify obsolete content and documentation gaps

**Input:** Quality scores + query logs
**Output:** Governance reports in API

**Deliverables:**
- `api/governance.py` - Governance endpoints
- `governance/obsolete_detector.py` - Flag old/low-quality docs
- `governance/gap_analyzer.py` - Find unanswered queries

**Test:**
```bash
curl http://localhost:8000/api/v1/governance/obsolete
# Returns: List of obsolete documents
curl http://localhost:8000/api/v1/governance/gaps
# Returns: Common queries with no good answers
```

**Idempotent:** Yes - reports generated from current state

---

### Phase 13: Web UI
**Goal:** Simple web interface for search and admin

**Input:** User interactions
**Output:** Web pages

**Deliverables:**
- `frontend/index.html` - Search interface
- `frontend/admin.html` - Governance dashboard
- Static file serving in FastAPI

**Test:**
```
Open http://localhost:3000
Search works, governance reports visible
```

**Idempotent:** Yes - UI is stateless

---

## Phase Summary

| Phase | Deliverable | Test Command |
|-------|-------------|--------------|
| 1 | Infrastructure | `curl /health` |
| 2 | Confluence Download | `kb-download` |
| 3 | Content Parsing | `kb-parse` |
| 4 | Metadata Generation | `kb-metadata` |
| 5 | Vector Indexing | `kb-index` |
| 6 | Search API | `curl /api/v1/search` |
| 7 | RAG Answers | `curl /api/v1/search?include_answer=true` |
| 8 | Slack Bot | `/ask` in Slack |
| 9 | Permissions | Filtered results per user |
| 10 | Feedback | Click 👍/👎 |
| 11 | Quality Scoring | `kb-evaluate` |
| 12 | Governance | `curl /api/v1/governance/*` |
| 13 | Web UI | Browser test |

## Full Pipeline Test

After all phases, run end-to-end:

```bash
# 1. Start services
docker-compose up -d

# 2. Run full sync pipeline
python -m knowledge_base.cli sync --full

# 3. Test search
curl -X POST http://localhost:8000/api/v1/search \
  -d '{"query": "onboarding", "include_answer": true}'

# 4. Test in Slack
/ask What should a new employee read?
```

## Key Dependencies (Extended)

```toml
[project]
dependencies = [
    # Core
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",

    # Slack
    "slack-bolt>=1.18.0",
    "slack-sdk>=3.26.0",

    # AI/ML
    "chromadb>=0.4.22",
    "langchain>=0.1.0",
    "langchain-community>=0.0.10",
    "ollama>=0.1.6",
    "sentence-transformers>=2.2.0",

    # Confluence
    "atlassian-python-api>=3.41.0",

    # Database
    "sqlalchemy>=2.0.25",
    "aiosqlite>=0.19.0",

    # Task queue
    "celery[redis]>=5.3.0",
    "redis>=5.0.0",

    # Parsing
    "beautifulsoup4>=4.12.0",
    "html2text>=2024.2.26",
    "pypdf>=4.0.0",
    "python-docx>=1.1.0",
    "tiktoken>=0.5.2",

    # Auth
    "authlib>=1.3.0",
    "cryptography>=41.0.0",

    # Utils
    "httpx>=0.26.0",
    "tenacity>=8.2.0",
]
```

## Configuration (Extended)

```bash
# Slack
SLACK_BOT_TOKEN=xoxb-xxx
SLACK_APP_TOKEN=xapp-xxx
SLACK_SIGNING_SECRET=xxx

# Confluence
CONFLUENCE_URL=https://keboola.atlassian.net
CONFLUENCE_API_TOKEN=xxx

# Ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_EMBEDDING_MODEL=mxbai-embed-large
OLLAMA_LLM_MODEL=llama3.1:8b

# ChromaDB
CHROMA_HOST=chromadb
CHROMA_PORT=8000

# Redis
REDIS_URL=redis://redis:6379/0

# Scheduled Tasks
DAILY_EVALUATION_HOUR=3  # 3 AM
SYNC_INTERVAL_HOURS=6

# Feedback
OBSOLETE_THRESHOLD_DAYS=730  # 2 years
LOW_QUALITY_THRESHOLD=0.3    # quality_score < 0.3
```

## Governance Features

### Obsolete Content Detection

Documents flagged as obsolete when:
- Last updated > 2 years ago AND
- Quality score < 0.5 OR
- Negative feedback ratio > 50%

### Gap Analysis

Track queries that:
- Return no results
- Get thumbs down
- Lead to follow-up questions

Surface as "documentation gaps" for content creators.

### Quality Dashboard

- Top performing documents (high quality score)
- Documents needing updates (low quality, old)
- Trending topics (frequent queries)
- Coverage analysis (topics with/without docs)

## Prompt Engineering

### Metadata Extraction Prompt

```
Analyze this Confluence document and extract structured metadata.

Document:
{content}

Extract:
1. topics: 3-5 main topics (e.g., ["onboarding", "benefits", "PTO"])
2. intents: 2-3 use cases when this doc is useful (e.g., ["new_employee", "requesting_time_off"])
3. audience: Who should read this (e.g., ["all_employees", "engineering"])
4. doc_type: One of: policy, how-to, reference, FAQ, announcement, meeting-notes
5. key_entities: Products, services, tools, locations mentioned
6. summary: 1-2 sentence summary

Return as JSON.
```

### Answer Generation Prompt

```
You are Keboola's knowledge base assistant.
Answer based ONLY on the provided context.

Context documents:
{documents_with_metadata}

User question: {query}

Guidelines:
1. Cite sources: [Page Title](url)
2. Warn if sources are outdated (> 1 year old)
3. If unsure, say "I couldn't find this in the knowledge base"
4. Never invent information
5. Mention document freshness if relevant
```

## Learning Loop Summary

```
     User asks question
            │
            ▼
    RAG generates answer
    (with source citations)
            │
            ▼
    User provides feedback
    ├── 👍 Thumbs up (+1.0)
    ├── 👎 Thumbs down (-1.0)
    ├── 💡 Suggestion (text)
    ├── Follow-up question (-0.3)
    └── Link click (+0.2)
            │
            ▼
    Feedback stored in DB
            │
            ▼
    Daily Re-evaluation
    ├── Update quality_score per document
    ├── Update relevance_score
    ├── Flag obsolete content
    ├── Identify gaps
    └── Refine topic clusters
            │
            ▼
    Better answers tomorrow
```

---

## Design Decisions & Clarifications

### Provider Abstraction (Production-Ready)

All AI/ML components use **abstract base classes** for easy switching between providers:

```python
# Abstract interfaces for swappable providers

class BaseLLM(ABC):
    @abstractmethod
    async def generate(self, prompt: str, context: list[str]) -> str: ...

class BaseEmbeddings(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class BaseVectorStore(ABC):
    @abstractmethod
    async def search(self, query_embedding: list[float], k: int) -> list[Document]: ...
```

| Component | Dev/Local | Production Options |
|-----------|-----------|-------------------|
| LLM | Ollama (llama3.1) | OpenAI, Anthropic, Google AI |
| Embeddings | Ollama (mxbai-embed) | OpenAI, Cohere, Google |
| Vector Store | ChromaDB | pgvector, Weaviate, Pinecone |

### Sync Clarification: One-Way with Deletion

**Clarification:** This is a **one-way sync** (Confluence → Knowledge Base), not two-way.
- We do NOT write back to Confluence
- "Deletion handling" means: if a page is deleted in Confluence, we remove it from our index

```
Sync Flow:
1. Fetch all page IDs from Confluence
2. Compare with local index
3. ADD: New pages in Confluence → index them
4. UPDATE: Changed pages → re-index
5. DELETE: Pages removed from Confluence → delete from index
```

### Initial User Experience (Before First Sync)

When the bot is first installed and no content is indexed:

```
User: /ask How do I request PTO?

Bot: 🔄 The knowledge base is currently being initialized.
     This is a one-time process that takes about X minutes.

     Status: Syncing Confluence spaces...
     Progress: 150/500 pages indexed

     Please try again in a few minutes, or I'll notify you when ready.
     [🔔 Notify me when ready]
```

### Secrets Management (Production)

**Critical:** Encryption keys must NOT be in `.env` or version control.

| Environment | Secrets Storage |
|-------------|-----------------|
| Development | `.env` file (local only, gitignored) |
| Staging | Environment variables in Docker/K8s |
| Production | HashiCorp Vault / AWS KMS / GCP Secret Manager |

```python
# Example: secrets.py
class SecretsManager(ABC):
    @abstractmethod
    def get_encryption_key(self) -> bytes: ...

class VaultSecretsManager(SecretsManager):
    """Production: HashiCorp Vault"""

class EnvSecretsManager(SecretsManager):
    """Development: .env file"""
```

### Content Parsing Details

#### Confluence Macros Handling

| Macro Type | Handling Strategy |
|------------|-------------------|
| `{code}` | Preserve as code block, mark `chunk_type="code"` |
| `{info}`, `{warning}`, `{note}` | Extract inner content, add prefix |
| `{expand}` | Expand and include content |
| `{panel}` | Extract inner content |
| `{toc}` | Skip (auto-generated) |
| `{children}` | Skip (navigational) |
| `{excerpt}` | Include as summary candidate |

#### Table Handling

Tables are notoriously difficult for RAG. Strategy:

```
Option A: Keep tables intact
- Store entire table as one chunk
- Convert to markdown format
- Add table context (surrounding headers/text)

Option B: Row-based with context
- Each row becomes a chunk
- Prepend column headers to each row
- Include table title/caption
```

**Recommendation:** Option A for tables < 20 rows, Option B for larger tables.

#### Attachments

| File Type | Handling |
|-----------|----------|
| PDF | Extract text with pypdf, chunk like pages |
| DOCX | Extract text with python-docx |
| XLSX | Convert to markdown tables |
| Images | Index alt-text and surrounding context |
| Other | Skip, log for review |

**Limits:**
- Max file size: 10MB
- Processing timeout: 60 seconds
- Skip files that fail, log error, continue sync

### Vocabulary Normalization

To prevent messy metadata ("engineering" vs "engineers" vs "eng"):

```python
# Canonical vocabulary mappings
TOPIC_SYNONYMS = {
    "engineering": ["engineers", "eng", "development", "dev"],
    "onboarding": ["new hire", "new employee", "getting started"],
    "benefits": ["perks", "compensation"],
}

AUDIENCE_CANONICAL = [
    "all_employees",
    "engineering",
    "sales",
    "hr",
    "leadership",
    "new_hires",
]

# Normalization happens after LLM extraction
def normalize_topics(raw_topics: list[str]) -> list[str]:
    # Map to canonical form, or create new if truly novel
```

**Daily job:** Review new non-canonical terms, suggest additions to vocabulary.

### Conversation Context Storage

| Storage | Duration | Use Case |
|---------|----------|----------|
| In-memory (per thread) | 30 minutes | Active conversation follow-ups |
| Redis | 24 hours | Cross-session context |
| SQLite | Permanent | Analytics, training data |

```python
class ConversationManager:
    def __init__(self, redis_client, db_session):
        self.redis = redis_client
        self.db = db_session

    async def get_context(self, thread_ts: str) -> list[Message]:
        # Try in-memory first, then Redis, then DB

    async def add_message(self, thread_ts: str, message: Message):
        # Store in all layers
```

### Suggestion Workflow

When user clicks `💡 Suggest improvement`:

```
1. Bot opens modal for text input
2. User submits suggestion
3. Create record in `governance_issues` table:
   - issue_type: "user_suggestion"
   - page_ids: documents shown in response
   - suggestion_text: user's input
   - user_id: who suggested
4. Weekly digest email to content owners
5. Optionally: Create Jira ticket via webhook
```

### Rate Limiting Strategy

```python
# Confluence API rate limiting
from tenacity import retry, wait_exponential, stop_after_attempt

@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(RateLimitError)
)
async def fetch_page(page_id: str):
    response = await client.get(f"/content/{page_id}")
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        raise RateLimitError(retry_after)
    return response.json()
```

**Sync throttling:**
- Batch size: 50 pages per batch
- Delay between batches: 1 second
- Respect `Retry-After` headers
- Log rate limit events for monitoring

### Permission Caching

Checking permissions for every document on every query is expensive.

```python
class PermissionCache:
    """Cache user permissions with TTL"""

    def __init__(self, redis: Redis, ttl_seconds: int = 300):  # 5 min TTL
        self.redis = redis
        self.ttl = ttl_seconds

    async def can_access(self, user_id: str, page_id: str) -> bool | None:
        key = f"perm:{user_id}:{page_id}"
        cached = await self.redis.get(key)
        if cached is not None:
            return cached == "1"
        return None  # Cache miss, need to check Confluence

    async def set_access(self, user_id: str, page_id: str, can_access: bool):
        key = f"perm:{user_id}:{page_id}"
        await self.redis.setex(key, self.ttl, "1" if can_access else "0")
```

**Strategy:**
1. Check cache first (5 min TTL)
2. On cache miss, query Confluence
3. Cache result
4. Invalidate on user re-authentication

---

## Testing Strategy

### Test Structure

```
tests/
├── unit/                      # Fast, isolated tests
│   ├── test_chunking.py
│   ├── test_metadata_extractor.py
│   ├── test_permission_cache.py
│   └── test_vocabulary_normalizer.py
│
├── integration/               # Component interaction tests
│   ├── test_confluence_sync.py
│   ├── test_chromadb_indexer.py
│   ├── test_rag_pipeline.py
│   └── test_feedback_loop.py
│
├── e2e/                       # Full system tests
│   ├── test_slack_commands.py
│   ├── test_search_flow.py
│   └── test_governance_workflow.py
│
├── conftest.py                # Shared fixtures
└── docker-compose.test.yml    # Test environment
```

### Test Categories

| Type | Tools | Run When |
|------|-------|----------|
| Unit | pytest, pytest-asyncio | Every commit |
| Integration | pytest + testcontainers | PR merge |
| E2E | pytest + Slack test workspace | Pre-release |
| Load | locust | Weekly / before release |

### Key Test Scenarios

1. **Chunking:** Tables stay intact, code blocks preserved
2. **Permissions:** Unauthorized docs filtered correctly
3. **Feedback:** Quality scores update correctly
4. **Sync:** Deletions handled, rate limits respected
5. **RAG:** Relevant docs retrieved, sources cited

---

## Monitoring & Observability

### Structured Logging

```python
import structlog

logger = structlog.get_logger()

# Every log includes context
logger.info(
    "search_completed",
    user_id=user_id,
    query=query[:50],
    num_results=len(results),
    latency_ms=latency,
    model=config.llm_model,
)
```

### Metrics (Prometheus)

```python
from prometheus_fastapi_instrumentator import Instrumentator

# Auto-instrument FastAPI
Instrumentator().instrument(app).expose(app)

# Custom metrics
from prometheus_client import Counter, Histogram

search_latency = Histogram(
    "kb_search_latency_seconds",
    "Search request latency",
    ["has_answer"]
)

feedback_counter = Counter(
    "kb_feedback_total",
    "Feedback events",
    ["type"]  # thumbs_up, thumbs_down, suggestion
)

llm_tokens = Counter(
    "kb_llm_tokens_total",
    "LLM token usage",
    ["operation"]  # metadata_extraction, answer_generation
)
```

### Key Metrics to Track

| Metric | Purpose |
|--------|---------|
| `kb_search_latency_seconds` | Performance monitoring |
| `kb_permission_check_latency` | Permission bottleneck detection |
| `kb_feedback_total` | User satisfaction |
| `kb_llm_tokens_total` | Cost monitoring |
| `kb_sync_pages_total` | Sync health |
| `kb_sync_errors_total` | Sync reliability |

### Health Endpoints

```
GET /health         → Basic health (always fast)
GET /health/ready   → All dependencies ready
GET /health/live    → Kubernetes liveness probe
GET /metrics        → Prometheus metrics
```

---

## Dependencies (Complete)

```toml
[project]
dependencies = [
    # ... (existing dependencies)
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "testcontainers>=3.7.0",
    "ruff>=0.1.0",
    "black>=24.0.0",
    "mypy>=1.8.0",
    "pre-commit>=3.6.0",
]

test = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "httpx>=0.26.0",  # For TestClient
    "testcontainers>=3.7.0",
]

monitoring = [
    "prometheus-fastapi-instrumentator>=6.1.0",
    "structlog>=24.1.0",
    "opentelemetry-api>=1.22.0",
    "opentelemetry-sdk>=1.22.0",
]
```

---

## Risk Mitigation Summary

| Risk | Mitigation |
|------|------------|
| LLM costs in production | Token usage monitoring, budget alerts |
| ChromaDB scalability | Abstract interface, migration path to pgvector |
| Confluence rate limits | Exponential backoff, batch throttling |
| Permission complexity | Caching with TTL, efficient bulk checks |
| Messy vocabulary | Normalization, canonical mappings |
| Secrets exposure | Vault/KMS for production, never in .env |
