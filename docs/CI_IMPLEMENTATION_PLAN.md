# CI/CD Pipeline Implementation Plan (Production-Grade)

## Overview

Full CI/CD pipeline with staging environment. Code is tested locally in CI, then deployed to staging for E2E tests against real infrastructure, then promoted to production. Staging has its own ChromaDB and Slack app - production data is never touched during testing.

## Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                    GitHub Actions                        │
                    ├─────────────────────────────────────────────────────────┤
                    │  1. Unit Tests (container)                              │
                    │  2. Build Docker images                                 │
                    │  3. Deploy to Staging                                   │
                    │  4. E2E Tests against Staging                           │
                    │  5. Deploy to Production (if staging tests pass)        │
                    └─────────────────────────────────────────────────────────┘
                                            │
                    ┌───────────────────────┴───────────────────────┐
                    ▼                                               ▼
        ┌───────────────────────┐                   ┌───────────────────────┐
        │      STAGING          │                   │     PRODUCTION        │
        ├───────────────────────┤                   ├───────────────────────┤
        │ slack-bot-staging     │                   │ slack-bot             │
        │ chromadb-staging      │                   │ chromadb              │
        │ Test Slack App        │                   │ Production Slack App  │
        │ #bot-testing channel  │                   │ Real channels         │
        └───────────────────────┘                   └───────────────────────┘
```

## Implementation Checklist

### Phase 1: Create Staging Infrastructure (Terraform)

- [ ] Create `deploy/terraform/cloudrun-slack-staging.tf` (copy of production with `-staging` suffix)
- [ ] Create `deploy/terraform/cloudrun-chromadb-staging.tf` (staging ChromaDB)
- [ ] Add staging environment variables to Terraform
- [ ] Run `terraform apply` to create staging infrastructure

**File: `deploy/terraform/cloudrun-slack-staging.tf`:**
```hcl
resource "google_cloud_run_service" "slack_bot_staging" {
  name     = "slack-bot-staging"
  location = var.region
  # ... same config as production but with staging env vars
  template {
    spec {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/slack-bot:staging"
        env {
          name  = "CHROMADB_HOST"
          value = "https://chromadb-staging-${var.project_number}.run.app"
        }
        env {
          name  = "ENVIRONMENT"
          value = "staging"
        }
      }
    }
  }
}
```

### Phase 2: Create Staging Slack App

- [ ] Go to https://api.slack.com/apps
- [ ] Create new app "Knowledge Base (Staging)"
- [ ] Configure same scopes as production app
- [ ] Set Request URL to staging Cloud Run URL
- [ ] Install to workspace
- [ ] Create dedicated `#bot-testing` channel
- [ ] Note down staging bot tokens

### Phase 3: Create GitHub Actions Workflow

- [ ] Create directory `.github/workflows/`
- [ ] Create file `.github/workflows/ci.yml` with content below

**File: `.github/workflows/ci.yml`:**

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  PROJECT_ID: ai-knowledge-base-42
  REGION: us-central1

jobs:
  # ============================================
  # Stage 1: Unit Tests (runs on every PR/push)
  # ============================================
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e .[dev]
      - name: Run unit tests
        run: pytest tests/ --ignore=tests/e2e --ignore=tests/integration -v

  # ============================================
  # Stage 2: Build Docker Images
  # ============================================
  build:
    needs: unit-tests
    runs-on: ubuntu-latest
    outputs:
      image_tag: ${{ steps.meta.outputs.tags }}
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      - uses: google-github-actions/setup-gcloud@v2
      - name: Configure Docker
        run: gcloud auth configure-docker ${{ env.REGION }}-docker.pkg.dev
      - name: Build and push images
        run: |
          TAG="${{ github.sha }}"
          docker build -f deploy/docker/Dockerfile.slack -t ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/knowledge-base/slack-bot:$TAG .
          docker push ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/knowledge-base/slack-bot:$TAG

  # ============================================
  # Stage 3: Deploy to Staging
  # ============================================
  deploy-staging:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      - uses: google-github-actions/setup-gcloud@v2
      - name: Deploy to staging
        run: |
          gcloud run deploy slack-bot-staging \
            --image=${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/knowledge-base/slack-bot:${{ github.sha }} \
            --region=${{ env.REGION }} \
            --project=${{ env.PROJECT_ID }}

  # ============================================
  # Stage 4: E2E Tests against Staging
  # ============================================
  e2e-tests-staging:
    needs: deploy-staging
    runs-on: ubuntu-latest
    env:
      SLACK_BOT_TOKEN: ${{ secrets.STAGING_SLACK_BOT_TOKEN }}
      SLACK_USER_TOKEN: ${{ secrets.STAGING_SLACK_USER_TOKEN }}
      E2E_TEST_CHANNEL_ID: ${{ secrets.STAGING_TEST_CHANNEL_ID }}
      E2E_BOT_USER_ID: ${{ secrets.STAGING_BOT_USER_ID }}
      CHROMADB_HOST: ${{ secrets.STAGING_CHROMADB_URL }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e .[dev]
      - name: Wait for staging to be ready
        run: sleep 30
      - name: Run E2E tests against staging
        run: pytest tests/e2e/test_knowledge_creation_live.py -v -m e2e

  # ============================================
  # Stage 5: Deploy to Production (main only)
  # ============================================
  deploy-production:
    needs: e2e-tests-staging
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      - uses: google-github-actions/setup-gcloud@v2
      - name: Deploy to production
        run: |
          gcloud run deploy slack-bot \
            --image=${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/knowledge-base/slack-bot:${{ github.sha }} \
            --region=${{ env.REGION }} \
            --project=${{ env.PROJECT_ID }}
```

### Phase 4: Configure GitHub Secrets

Go to: GitHub repo → Settings → Secrets and variables → Actions

**GCP Authentication:**
- [ ] `GCP_SA_KEY` - Service account JSON with Cloud Run deploy permissions

**Staging Slack App (for E2E tests):**
- [ ] `STAGING_SLACK_BOT_TOKEN` - Staging bot token (xoxb-...)
- [ ] `STAGING_SLACK_USER_TOKEN` - Staging user token (xoxp-...)
- [ ] `STAGING_TEST_CHANNEL_ID` - #bot-testing channel ID
- [ ] `STAGING_BOT_USER_ID` - Staging bot user ID
- [ ] `STAGING_CHROMADB_URL` - Staging ChromaDB Cloud Run URL

### Phase 5: Documentation

- [ ] Create `docs/adr/0007-github-actions-ci.md` documenting CI decision
- [ ] Create `docs/adr/0008-staging-environment.md` documenting staging setup
- [ ] Update README with CI/CD information

### Phase 6: Verification

- [ ] Verify staging infrastructure is running (`slack-bot-staging`, `chromadb-staging`)
- [ ] Verify staging Slack app responds in #bot-testing
- [ ] Create a test PR
- [ ] Verify unit tests run on PR
- [ ] Verify staging deployment happens
- [ ] Verify E2E tests run against staging
- [ ] Merge PR to main
- [ ] Verify production deployment happens after staging tests pass

## Pipeline Flow

### On Pull Request:
```
PR opened/updated
       ↓
  Unit tests run (in container)
       ↓
  Pass? ─── No ──→ PR blocked ✗
       ↓
  Build Docker image
       ↓
  Deploy to staging
       ↓
  E2E tests against staging (real Slack, real ChromaDB)
       ↓
  Pass? ─── No ──→ PR blocked ✗
       ↓
  PR shows ✓ ready to merge
```

### After Merge to Main:
```
Same pipeline as PR, plus:
       ↓
  E2E tests pass on staging
       ↓
  Deploy to production
       ↓
  Production updated ✓
```

## Infrastructure Summary

| Component | Staging | Production |
|-----------|---------|------------|
| Slack Bot | `slack-bot-staging` | `slack-bot` |
| ChromaDB | `chromadb-staging` | `chromadb` |
| Slack App | "Knowledge Base (Staging)" | "Knowledge Base" |
| Test Channel | `#bot-testing` | Real channels |
| Docker Tag | `slack-bot:$SHA` | `slack-bot:$SHA` |

## Cost Estimate

| Resource | Monthly Cost |
|----------|--------------|
| Cloud Run staging bot | ~$5-15 (low traffic) |
| Cloud Run staging ChromaDB | ~$10-20 |
| **Total additional** | **~$15-35/month** |

## Notes

- Same Docker image is deployed to staging then production (immutable artifact)
- Staging uses separate Slack app - production users never see test messages
- E2E tests run against real staging infrastructure, not mocks
- Production deploy only happens if staging E2E tests pass
- GitHub commit SHA used as image tag for traceability
