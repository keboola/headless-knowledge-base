#!/usr/bin/env bash
# Fetch staging secrets from GCP Secret Manager and write to .env.e2e
#
# Usage: ./scripts/setup-e2e-env.sh
#
# Prerequisites:
#   - gcloud CLI authenticated: gcloud auth login
#   - Access to project ai-knowledge-base-42
#
# This script fetches the staging Slack signing secret from Secret Manager
# and adds it to .env.e2e so that e2e button-click tests can sign requests
# correctly against the staging bot.

set -euo pipefail

PROJECT="ai-knowledge-base-42"
ENV_FILE=".env.e2e"

echo "Fetching staging secrets from Secret Manager (project: $PROJECT)..."

# Fetch the staging signing secret
SIGNING_SECRET=$(gcloud secrets versions access latest \
  --secret="slack-signing-secret-staging" \
  --project="$PROJECT" 2>/dev/null) || {
  echo "ERROR: Failed to fetch slack-signing-secret-staging. Are you authenticated?"
  echo "  Run: gcloud auth login"
  exit 1
}

# Update or append SLACK_STAGING_SIGNING_SECRET in .env.e2e
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found. Create it first with base e2e config."
  exit 1
fi

if grep -q "^SLACK_STAGING_SIGNING_SECRET=" "$ENV_FILE" 2>/dev/null; then
  # Update existing value
  sed -i "s|^SLACK_STAGING_SIGNING_SECRET=.*|SLACK_STAGING_SIGNING_SECRET=$SIGNING_SECRET|" "$ENV_FILE"
  echo "Updated SLACK_STAGING_SIGNING_SECRET in $ENV_FILE"
else
  # Append new value
  echo "SLACK_STAGING_SIGNING_SECRET=$SIGNING_SECRET" >> "$ENV_FILE"
  echo "Added SLACK_STAGING_SIGNING_SECRET to $ENV_FILE"
fi

echo "Done. Run e2e tests with:"
echo "  set -a && source .env.e2e && set +a && python -m pytest tests/e2e/ -v"
