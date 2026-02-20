# AI Knowledge Base System - Security Context

## System Overview

AI-powered knowledge base seeded from Confluence, with Slack bot interface, RAG pipeline, and Graphiti/Neo4j temporal knowledge graph. Deployed on Google Cloud (Cloud Run services + GCE VMs).

## Data Classification

### CRITICAL - Credentials
| Credential | Purpose | Risk if Exposed |
|------------|---------|-----------------|
| `SLACK_BOT_TOKEN` | Slack workspace API access (xoxb-) | Bot impersonation, channel data access |
| `SLACK_SIGNING_SECRET` | HMAC request verification | Request spoofing as Slack |
| `ANTHROPIC_API_KEY` | Claude LLM inference | Unauthorized API usage, cost |
| `CONFLUENCE_API_TOKEN` | Confluence page download | Access to all company wiki content |
| `CONFLUENCE_USERNAME` | Confluence Basic Auth | Auth component |
| `NEO4J_PASSWORD` | Graph database access | Full knowledge graph read/write |
| `GCP_SA_KEY` | GCP service account JSON | Cloud resource access |

### HIGH - PII / Sensitive Content
- Slack user IDs and usernames (stored in Neo4j episode metadata as reporter_id, reporter_name)
- Slack channel IDs (stored in episode metadata)
- Confluence page content (company internal documentation)
- Author names from Confluence pages
- LLM prompt/response content (may contain internal docs)

### MEDIUM - Operational Data
- Neo4j episode metadata (page_id, space_key, chunk_type)
- Search queries from Slack users
- Quality scores and feedback data
- Pipeline checkpoint state

## Sensitive Operations

### Slack Bot (`src/knowledge_base/slack/bot.py`)
- OAuth token for posting answers, updating messages, reading history
- HMAC verification via SLACK_SIGNING_SECRET
- User questions forwarded to LLM with retrieved context

### Confluence Sync (`src/knowledge_base/confluence/client.py`)
- Basic Auth with CONFLUENCE_USERNAME + CONFLUENCE_API_TOKEN
- Downloads all pages from configured spaces
- Content stored in Neo4j as Graphiti episodes

### Neo4j / Graphiti (`src/knowledge_base/graph/`)
- Bolt protocol connections with NEO4J_PASSWORD
- Stores: document chunks, entity nodes, relationship edges, vector embeddings
- PII in metadata: reporter_id, reporter_name, channel_id, author

### LLM API Calls (`src/knowledge_base/rag/providers/`)
- Anthropic Claude: Direct API key authentication
- Google Gemini: Vertex AI service account auth
- Document content sent to external APIs for entity extraction and answer generation

### Admin UI (`src/knowledge_base/app/`)
- ADMIN_USERNAME/ADMIN_PASSWORD for Streamlit dashboard
- Default ADMIN_PASSWORD is "changeme" (validated at runtime in config.py)

### Pipeline Checkpoints (`src/knowledge_base/graph/graphiti_indexer.py`)
- SQLite DB persisted to GCS FUSE mount
- WAL checkpoint before copy (PRAGMA wal_checkpoint)
- Crash-resilient resume state

## Security Patterns to Preserve

1. **pydantic-settings for all config** - Never hardcode credentials
2. **ADMIN_PASSWORD runtime validation** - config.py model_validator warns if "changeme"
3. **NullPool for SQLite** - Prevents WAL lock retention
4. **SLACK_SIGNING_SECRET verification** - All Slack requests HMAC-verified
5. **VPC internal access for Neo4j** - bolt:// over private network, not public
6. **Cloud Armor WAF** - Rate limiting on public endpoints
7. **Secret Manager for production secrets** - Not env vars or tfvars

## Anti-Patterns to Flag

### CRITICAL - Must Block PR
1. Logging any token, password, or API key at any level
2. Hardcoding real credentials in code
3. Removing SLACK_SIGNING_SECRET verification
4. Exposing Neo4j Bolt port publicly

### HIGH - Should Request Changes
1. Logging Slack user PII (user_id, username) at info level
2. Sending unvalidated user input to LLM prompts without sanitization
3. Missing error handling that could expose credentials in stack traces
4. Terraform changes that widen IAM permissions unnecessarily

### MEDIUM - Should Comment
1. Missing audit logging for privileged operations
2. Overly broad exception handling
3. SQLite operations without proper WAL checkpoint handling
4. GCS FUSE file operations without error handling
