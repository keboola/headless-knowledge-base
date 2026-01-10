# ADR 0007: GitHub Actions CI/CD Pipeline

## Status
Accepted

## Context
We need automated testing and deployment to ensure code quality and reduce manual deployment effort. The system is becoming production-critical for the company, requiring reliable and consistent deployment processes.

Previously, deployments were manual:
```bash
gcloud builds submit --project=ai-knowledge-base-42 --config=cloudbuild.yaml .
```

This approach has risks:
- Developers might forget to run tests before deploying
- No consistent verification across the team
- No audit trail of what was deployed and when
- Production can be broken by untested code

## Decision
Implement a 5-stage GitHub Actions CI/CD pipeline:

1. **Unit Tests** - Run on every PR and push to main
2. **Build** - Build Docker images and push to Artifact Registry
3. **Deploy to Staging** - Deploy to staging environment for E2E testing
4. **E2E Tests** - Run against staging with real Slack and ChromaDB
5. **Deploy to Production** - Only on main branch after staging tests pass

### Workflow Triggers
- Pull Requests: Stages 1-4 (tests and staging validation)
- Push to main: Stages 1-5 (full pipeline including production deploy)

### Key Design Decisions
- **Same image for staging and production**: Immutable artifacts ensure what's tested is what's deployed
- **GitHub commit SHA as image tag**: Full traceability from deployment to code
- **Secrets in GitHub Secrets**: Simple, secure, no external secret management needed
- **Staging E2E tests before production**: Catch issues that only appear in cloud environment

## Consequences

### Positive
- Automated testing on every PR prevents broken code from merging
- Consistent deployment process across all team members
- Full audit trail in GitHub Actions logs
- Staging validation catches cloud-specific issues before production
- Faster feedback loop for developers

### Negative
- CI/CD adds ~5-10 minutes to the deployment process
- Requires GitHub Secrets configuration (one-time setup)
- Staging infrastructure has ongoing cost (~$15-35/month)
- Team needs to learn GitHub Actions workflow syntax

### Neutral
- Requires staging Slack app setup (separate from production)
- Need to maintain two environments (staging + production)

## References
- GitHub Actions documentation: https://docs.github.com/en/actions
- Google Cloud Run deployment: https://cloud.google.com/run/docs/deploying
- Related: ADR 0008 (Staging Environment)
