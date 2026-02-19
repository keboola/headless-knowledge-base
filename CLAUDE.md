# AI Knowledge Base - Agent Instructions

## Project Overview

AI-powered knowledge base seeded from Confluence, with Slack bot interface, RAG pipeline, and Graphiti/Neo4j knowledge graph.

- **GCP Project**: `ai-knowledge-base-42`, region `us-central1`
- **Architecture doc**: `docs/ARCHITECTURE.md` (read this first)
- **ADRs**: `docs/adr/` (design decisions and rationale)

## Git Workflow

- **NEVER push directly to `main`** — always create a feature branch and open a PR
- Branch naming: `feature/`, `fix/`, `chore/`, `refactor/` prefixes
- CI/CD runs on every push: unit tests, build, deploy staging, e2e tests, deploy production
- PRs require passing CI before merge

```bash
git checkout -b feature/my-change
# ... make changes ...
git push -u origin feature/my-change
gh pr create --title "Add my change" --body "..."
```

## Tech Stack

| Component | Technology | Notes |
|-----------|------------|-------|
| Knowledge Graph | Neo4j 5.26 + Graphiti-core | Source of truth for all knowledge data |
| Metadata DB | SQLite + SQLAlchemy 2.0 async (NullPool) | Page sync, checkpoints, feedback |
| LLM | Gemini 2.5 Flash (Vertex AI) | Entity extraction, answer generation |
| Embeddings | Vertex AI text-embedding-005 | 768-dim vectors |
| Bot | Slack Bolt (HTTP mode) | Primary user interface |
| Infra | Cloud Run (bot, jobs) + GCE (Neo4j) | Terraform in `deploy/terraform/` |

## Key Conventions

### Code

- Python 3.11, async/await for I/O
- Type hints on all function signatures
- `pydantic-settings` for config — all settings via environment variables, no hardcoded values
- SQLite uses NullPool (connections close immediately) and WAL mode
- Checkpoint writes use raw `aiosqlite` (bypass SQLAlchemy to avoid lock contention)
- Tests in `tests/` — unit, integration, e2e subdirectories

### Pipeline

- CLI: `python -m knowledge_base.cli pipeline`
- Steps: download (Confluence) -> parse (chunks) -> index (Graphiti)
- `ConfluenceDownloader(index_to_graphiti=False)` in pipeline — Step 3 handles indexing
- Checkpoints persisted to GCS FUSE after every batch (see ADR-0010)
- Resume is automatic — already-indexed chunks are skipped on restart

### Docker Images

Two separate images — must rebuild both when code changes:
- `Dockerfile.jobs` -> `jobs:latest` (pipeline, background tasks)
- `Dockerfile.slack` -> `slack-bot:latest` (Slack bot service)

### Environments

- **Staging**: Neo4j at `bolt+s://neo4j.staging.keboola.dev:443`
- **Production**: Neo4j at `bolt://10.0.0.27:7687` (internal VPC)
- Always test on staging first before production
- Use `--dry-run` when available

### Terraform

- Located in `deploy/terraform/`
- `google-beta` provider required for GCS FUSE volumes
- Run `terraform plan` before `terraform apply`
- State locks can go stale — use `terraform force-unlock` if needed

## Testing

```bash
# Unit + integration tests
python -m pytest tests/ -v

# E2E tests (needs staging secrets)
./scripts/setup-e2e-env.sh
set -a && source .env.e2e && set +a
python -m pytest tests/e2e/ -v
```

## Common Operations

```bash
# Check pipeline job
gcloud run jobs executions list --job=sync-pipeline --region=us-central1 --project=ai-knowledge-base-42 --limit=5

# Check staging sync
gcloud run jobs executions list --job=confluence-sync-staging --region=us-central1 --project=ai-knowledge-base-42 --limit=5

# Build and push jobs image
printf 'steps:\n  - name: "gcr.io/cloud-builders/docker"\n    args: ["build", "-t", "us-central1-docker.pkg.dev/ai-knowledge-base-42/knowledge-base/jobs:latest", "-f", "deploy/docker/Dockerfile.jobs", "."]\nimages:\n  - "us-central1-docker.pkg.dev/ai-knowledge-base-42/knowledge-base/jobs:latest"\n' | gcloud builds submit --config /dev/stdin --project=ai-knowledge-base-42 .

# Build and push slack-bot image
printf 'steps:\n  - name: "gcr.io/cloud-builders/docker"\n    args: ["build", "-t", "us-central1-docker.pkg.dev/ai-knowledge-base-42/knowledge-base/slack-bot:latest", "-f", "deploy/docker/Dockerfile.slack", "."]\nimages:\n  - "us-central1-docker.pkg.dev/ai-knowledge-base-42/knowledge-base/slack-bot:latest"\n' | gcloud builds submit --config /dev/stdin --project=ai-knowledge-base-42 .
```
