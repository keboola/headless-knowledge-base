#!/bin/bash
# =============================================================================
# Update Secret Values in Secret Manager
# =============================================================================
# This script populates secret values in GCP Secret Manager.
# Run this after terraform apply.
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ai-knowledge-base-42}"

echo "=========================================="
echo "Updating secret values in Secret Manager"
echo "Project: $PROJECT_ID"
echo "=========================================="
echo ""
echo "You will be prompted for each value."
echo "Press Ctrl+C to cancel at any time."
echo ""

# Function to update a secret value
update_value() {
    local name=$1
    local prompt=$2
    local is_sensitive=${3:-true}

    echo "----------------------------------------"
    if [[ "$is_sensitive" == "true" ]]; then
        read -sp "$prompt: " value
        echo ""
    else
        read -p "$prompt: " value
    fi

    if [[ -z "$value" ]]; then
        echo "Skipping $name (empty value)"
        return
    fi

    echo "Updating: $name"
    echo -n "$value" | gcloud secrets versions add "$name" \
        --data-file=- \
        --project="$PROJECT_ID"

    echo "Value for $name updated successfully."
}

# Slack configuration
echo ""
echo "=== Slack Configuration ==="
update_value "slack-bot-token" "Enter Slack Bot Token (xoxb-...)"
update_value "slack-signing-secret" "Enter Slack Signing Secret"

# Anthropic configuration
echo ""
echo "=== Anthropic Configuration ==="
update_value "anthropic-api-key" "Enter Anthropic API Key (sk-ant-...)"

# Confluence configuration
echo ""
echo "=== Confluence Configuration ==="
update_value "confluence-email" "Enter Confluence Email" false
update_value "confluence-api-token" "Enter Confluence API Token"

# ChromaDB configuration
echo ""
echo "=== ChromaDB Configuration ==="
echo "Generating random ChromaDB token..."
CHROMADB_TOKEN=$(openssl rand -hex 32)
echo -n "$CHROMADB_TOKEN" | gcloud secrets versions add "chromadb-token" \
    --data-file=- \
    --project="$PROJECT_ID"
echo "ChromaDB token generated and saved."
echo "Token: $CHROMADB_TOKEN"
echo "(Save this token if you need to access ChromaDB directly)"

echo ""
echo "=========================================="
echo "All values updated successfully!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Redeploy Cloud Run services:"
echo "   gcloud run services update slack-bot --region=us-central1"
echo "   gcloud run services update chromadb --region=us-central1"
echo ""
echo "2. Configure your Slack app:"
echo "   - Go to api.slack.com/apps"
echo "   - Set Event Subscriptions URL to your Cloud Run URL + /slack/events"
echo "   - Enable necessary bot scopes"
