#!/bin/bash
# =============================================================================
# Helper: Setup IAP Secrets
# =============================================================================
# This script helps creates the Secret Manager secrets required for Identity-Aware Proxy.
# =============================================================================

set -e

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 <CLIENT_ID> <CLIENT_SECRET>"
    echo ""
    echo "You must create these credentials in the Google Cloud Console first:"
    echo "1. Go to APIs & Services > OAuth consent screen (Create Internal brand)"
    echo "2. Go to APIs & Services > Credentials > Create Credentials > OAuth client ID"
    echo "3. Application type: Web application"
    echo "4. Name: Knowledge Base IAP"
    echo "5. Authorized redirect URIs: https://iap.googleapis.com/v1/oauth/clientIds/<CLIENT_ID>:handleRedirect"
    echo "   (You will know the <CLIENT_ID> only after creation, so create it first, then edit to add URI)"
    echo ""
    exit 1
fi

CLIENT_ID="$1"
CLIENT_SECRET="$2"
PROJECT_ID=$(gcloud config get-value project)

echo "Setting up IAP secrets for project: $PROJECT_ID"

# Function to create or update secret
create_secret() {
    local NAME=$1
    local VALUE=$2

    if gcloud secrets describe "$NAME" --project="$PROJECT_ID" &>/dev/null; then
        echo "Secret $NAME exists. Adding new version..."
        echo -n "$VALUE" | gcloud secrets versions add "$NAME" --data-file=- --project="$PROJECT_ID"
    else
        echo "Creating secret $NAME..."
        echo -n "$VALUE" | gcloud secrets create "$NAME" --data-file=- --project="$PROJECT_ID" --replication-policy="automatic"
    fi
}

create_secret "iap-client-id" "$CLIENT_ID"
create_secret "iap-client-secret" "$CLIENT_SECRET"

echo "----------------------------------------------------------------"
echo "✅ IAP Secrets created successfully."
echo "   - iap-client-id"
echo "   - iap-client-secret"
echo "----------------------------------------------------------------"
