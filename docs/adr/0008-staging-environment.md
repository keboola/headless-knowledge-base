# ADR 0008: Staging Environment for CI/CD

## Status
Accepted

## Context
E2E tests require real infrastructure (Slack, ChromaDB) to validate the full system behavior. Running tests against production would:
- Pollute production data with test artifacts
- Risk production stability during testing
- Send test messages to real users
- Make debugging failures harder (mixed with real traffic)

We need an isolated environment that mirrors production for safe testing.

## Decision
Create a complete staging environment on GCP that mirrors production:

### Infrastructure Components
| Component | Staging | Production |
|-----------|---------|------------|
| Slack Bot | `slack-bot-staging` | `slack-bot` |
| ChromaDB | `chromadb-staging` | `chromadb` |
| Storage | `*-chromadb-data-staging` | `*-chromadb-data` |
| Slack App | "Knowledge Base (Staging)" | "Knowledge Base" |
| Test Channel | `#bot-testing` | Real channels |

### Key Design Decisions

1. **Separate Slack App**: Staging has its own Slack app installed in the workspace. Test messages only appear in `#bot-testing` channel, never in production channels.

2. **Separate ChromaDB Instance**: Staging ChromaDB has its own data bucket. Test data never mixes with production knowledge base.

3. **Scale to Zero**: Staging services use `min_instance_count = 0` to reduce costs when not in use. Production keeps instances warm.

4. **30-day Data Retention**: Staging storage auto-deletes data after 30 days. No need for long-term test data.

5. **Shared Secrets for Read-Only Services**: Staging reuses the Anthropic API key (LLM is stateless). Each environment has its own Slack tokens and ChromaDB tokens.

6. **Same Docker Image**: Staging and production run the exact same Docker image (tagged with git SHA). Only environment variables differ.

## Consequences

### Positive
- Production data is never touched during CI/CD
- E2E tests run against real cloud infrastructure
- Developers can safely test in a production-like environment
- Failures in staging don't affect production users

### Negative
- Additional infrastructure cost (~$15-35/month)
- Requires maintaining a second Slack app
- Two environments to monitor and update
- Secrets need to be configured for both environments

### Neutral
- Staging may drift from production if not regularly used
- Test data accumulates (mitigated by 30-day retention)

## Infrastructure Cost Estimate

| Resource | Monthly Cost |
|----------|--------------|
| Cloud Run staging bot (scale to zero) | ~$5-15 |
| Cloud Run staging ChromaDB | ~$10-20 |
| Cloud Storage staging bucket | ~$1-5 |
| **Total** | **~$15-35/month** |

## Setup Checklist

### GCP Infrastructure
- [ ] Run `terraform apply` to create staging resources
- [ ] Verify `slack-bot-staging` and `chromadb-staging` are running

### Slack App
- [ ] Create new Slack app "Knowledge Base (Staging)"
- [ ] Configure same OAuth scopes as production
- [ ] Set Request URL to staging Cloud Run URL
- [ ] Install to workspace
- [ ] Create `#bot-testing` channel
- [ ] Add staging bot to `#bot-testing`

### GitHub Secrets
- [ ] `STAGING_SLACK_BOT_TOKEN`
- [ ] `STAGING_SLACK_USER_TOKEN`
- [ ] `STAGING_TEST_CHANNEL_ID`
- [ ] `STAGING_BOT_USER_ID`
- [ ] `STAGING_CHROMADB_URL`

## References
- Related: ADR 0007 (GitHub Actions CI/CD)
- Terraform config: `deploy/terraform/staging.tf`
