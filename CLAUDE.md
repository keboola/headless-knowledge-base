# Claude Code Instructions

## Git Workflow

**IMPORTANT: Never commit directly to `main` branch.**

- Always create a feature branch for any changes
- Branch naming: `feature/<description>`, `fix/<description>`, `chore/<description>`
- Create a Pull Request for review before merging to main
- Run tests before pushing: `pytest tests/e2e/test_knowledge_creation_live.py`

Example workflow:
```bash
git checkout -b feature/my-new-feature
# make changes
git add -A
git commit -m "Description of changes"
git push -u origin feature/my-new-feature
# Then create PR on GitHub
```

## Project Structure

- `src/knowledge_base/` - Main application code
- `src/knowledge_base/slack/` - Slack bot handlers
- `tests/e2e/` - End-to-end tests
- `deploy/terraform/` - GCP infrastructure
- `docs/adr/` - Architecture Decision Records

## Deployment

The Slack bot is deployed on GCP Cloud Run:
- Project: `ai-knowledge-base-42`
- Region: `us-central1`
- Service: `slack-bot`

To deploy after merging to main:
```bash
cd /home/coder/Devel/keboola/headless-knowledge-base
gcloud builds submit --project=ai-knowledge-base-42 --config=cloudbuild.yaml .
```

## Testing

Run E2E tests with:
```bash
set -a && source .env.e2e && set +a
.venv/bin/python -m pytest tests/e2e/test_knowledge_creation_live.py -v
```

## Key Configuration

- LLM Provider: Gemini (`gemini-2.0-flash`)
- Vector Store: ChromaDB on Cloud Run
- Database: Ephemeral DuckDB (analytics only)
