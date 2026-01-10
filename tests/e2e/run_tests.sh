#!/bin/bash
# Run E2E tests against staging or production environment
#
# Usage:
#   ./tests/e2e/run_tests.sh staging       # Run against staging
#   ./tests/e2e/run_tests.sh production    # Run against production
#   ./tests/e2e/run_tests.sh               # Default: staging

set -e

ENV="${1:-staging}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

case "$ENV" in
  staging)
    ENV_FILE=".env.e2e.staging"
    echo "Running E2E tests against STAGING environment..."
    ;;
  production|prod)
    ENV_FILE=".env.e2e"
    echo "Running E2E tests against PRODUCTION environment..."
    ;;
  *)
    echo "Unknown environment: $ENV"
    echo "Usage: $0 [staging|production]"
    exit 1
    ;;
esac

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found"
  echo ""
  echo "Create from example:"
  echo "  cp $ENV_FILE.example $ENV_FILE"
  echo "  # Then edit with your credentials"
  exit 1
fi

# Load environment variables
set -a
source "$ENV_FILE"
set +a

echo "Configuration:"
echo "  - ChromaDB: $CHROMA_HOST"
echo "  - Bot User ID: $E2E_BOT_USER_ID"
echo "  - Test Channel: $E2E_TEST_CHANNEL_ID"
echo ""

# Run tests
.venv/bin/python -m pytest tests/e2e/test_knowledge_creation_live.py -v "$@"
