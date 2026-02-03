#!/bin/bash
# =============================================================================
# Clear Neo4j Staging Data
# =============================================================================
# This script clears all data from staging Neo4j before running intake tests
# Usage: ./clear-neo4j-staging.sh
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ai-knowledge-base-42}"
INSTANCE_NAME="neo4j-staging"
ZONE="${ZONE:-us-central1-a}"

echo "=========================================="
echo "Clearing Neo4j Staging Data"
echo "Project: $PROJECT_ID"
echo "Instance: $INSTANCE_NAME"
echo "=========================================="
echo ""

# Option 1: Delete all nodes via Cypher (preserves database structure)
echo "[1/3] Connecting to Neo4j and deleting all data..."
gcloud compute ssh "${INSTANCE_NAME}" \
    --project="${PROJECT_ID}" \
    --zone="${ZONE}" \
    --command='docker exec neo4j-staging cypher-shell -u neo4j -p ${NEO4J_PASSWORD} "MATCH (n) DETACH DELETE n"' \
    || {
        echo "Warning: Could not connect via SSH. Trying alternative method..."
        echo ""
        echo "[1/3] Stopping Neo4j container..."
        gcloud compute ssh "${INSTANCE_NAME}" \
            --project="${PROJECT_ID}" \
            --zone="${ZONE}" \
            --command='docker stop neo4j-staging' || true

        echo "[2/3] Removing Neo4j data volume..."
        gcloud compute ssh "${INSTANCE_NAME}" \
            --project="${PROJECT_ID}" \
            --zone="${ZONE}" \
            --command='sudo rm -rf /data/neo4j/data/*'

        echo "[3/3] Restarting Neo4j container..."
        gcloud compute ssh "${INSTANCE_NAME}" \
            --project="${PROJECT_ID}" \
            --zone="${ZONE}" \
            --command='docker start neo4j-staging'
    }

echo ""
echo "=========================================="
echo "Neo4j staging data cleared successfully"
echo "=========================================="
echo ""
echo "To verify:"
echo "  gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} --project=${PROJECT_ID} \\"
echo "    --command='docker exec neo4j-staging cypher-shell -u neo4j \"MATCH (n) RETURN COUNT(n)\"'"
echo ""
