#!/bin/bash
# =============================================================================
# Complete Intake Pipeline Test - End-to-End
# =============================================================================
# This script orchestrates the complete testing workflow:
# 1. Clear Neo4j staging data
# 2. Configure Cloud Run job with performance settings
# 3. Run the Confluence intake pipeline
# 4. Monitor progress and collect metrics
#
# Usage: ./run-intake-test.sh [OPTIONS]
# Options:
#   --concurrency N   Concurrent chunks (default: 3)
#   --space SPACE     Confluence space (default: KI)
#   --resume          Resume from checkpoint instead of fresh start
#   --skip-clear      Skip Neo4j clear (use if already cleared)
#   --no-wait         Submit job but don't wait for completion
# =============================================================================

set -euo pipefail

# Configuration
PROJECT_ID="${PROJECT_ID:-ai-knowledge-base-42}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
INSTANCE_NAME="neo4j-staging"
JOB_NAME="confluence-sync"

# Options
CONCURRENCY=3
SPACE="KI"
RESUME=false
SKIP_CLEAR=false
NO_WAIT=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        --space)
            SPACE="$2"
            shift 2
            ;;
        --resume)
            RESUME=true
            shift
            ;;
        --skip-clear)
            SKIP_CLEAR=true
            shift
            ;;
        --no-wait)
            NO_WAIT=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Color output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_section() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

log_step() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

log_info() {
    echo -e "${YELLOW}ℹ${NC}  $1"
}

# Start
log_section "CONFLUENCE INTAKE PIPELINE TEST"
echo "Project:    $PROJECT_ID"
echo "Region:     $REGION"
echo "Job:        $JOB_NAME"
echo "Space:      $SPACE"
echo "Concurrency: $CONCURRENCY"
echo "Resume:     $RESUME"
echo ""

START_TIME=$(date +%s)

# Step 1: Clear Neo4j (unless resuming)
if [ "$SKIP_CLEAR" != "true" ] && [ "$RESUME" != "true" ]; then
    log_section "STEP 1/4: Clear Neo4j Staging Data"

    log_step "Clearing all nodes from Neo4j..."
    gcloud compute ssh "${INSTANCE_NAME}" \
        --project="${PROJECT_ID}" \
        --zone="${ZONE}" \
        --command='docker exec neo4j-staging cypher-shell -u neo4j -p ${NEO4J_PASSWORD} "MATCH (n) DETACH DELETE n"' \
        2>&1 | grep -E "(^[0-9]|^$)" || true

    log_step "Verifying Neo4j is cleared..."
    COUNT=$(gcloud compute ssh "${INSTANCE_NAME}" \
        --project="${PROJECT_ID}" \
        --zone="${ZONE}" \
        --command='docker exec neo4j-staging cypher-shell -u neo4j -p ${NEO4J_PASSWORD} "MATCH (n) RETURN COUNT(n)"' \
        2>&1 | grep -oE '^[0-9]+' | head -1 || echo "error")

    if [ "$COUNT" = "0" ]; then
        log_info "Neo4j cleared successfully (0 nodes)"
    else
        log_info "Warning: Expected 0 nodes but found $COUNT (may be async)"
    fi
else
    if [ "$SKIP_CLEAR" = "true" ]; then
        log_step "Skipping Neo4j clear (--skip-clear flag)"
    else
        log_step "Skipping Neo4j clear (resuming from checkpoint)"
    fi
fi

# Step 2: Configure Cloud Run Job
log_section "STEP 2/4: Configure Cloud Run Job"

log_step "Setting environment variables..."
log_info "GRAPHITI_CONCURRENCY=$CONCURRENCY"
log_info "GRAPHITI_INTER_CHUNK_DELAY=0.0"
log_info "GRAPHITI_RATE_LIMIT_THRESHOLD=5"
log_info "GRAPHITI_CIRCUIT_BREAKER_COOLDOWN=60"

gcloud run jobs update "$JOB_NAME" \
    --set-env-vars=GRAPHITI_CONCURRENCY=$CONCURRENCY,GRAPHITI_INTER_CHUNK_DELAY=0.0,GRAPHITI_RATE_LIMIT_THRESHOLD=5,GRAPHITI_CIRCUIT_BREAKER_COOLDOWN=60 \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    || log_info "Could not update job (may not exist or first run)"

# Step 3: Execute Job
log_section "STEP 3/4: Execute Confluence Intake Pipeline"

log_step "Submitting job to Cloud Run..."
if [ "$NO_WAIT" = "true" ]; then
    gcloud run jobs execute "$JOB_NAME" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --async

    log_info "Job submitted (async mode - not waiting for completion)"
    log_info "To monitor: gcloud logging read 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB_NAME\"' --follow"
else
    gcloud run jobs execute "$JOB_NAME" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --wait

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    MINUTES=$((DURATION / 60))
    SECONDS=$((DURATION % 60))

    log_step "Job execution completed"
    log_info "Total duration: ${MINUTES}m ${SECONDS}s"
fi

# Step 4: Collect Metrics
log_section "STEP 4/4: Collect Metrics & Verify Results"

if [ "$NO_WAIT" != "true" ]; then
    log_step "Fetching job logs (last 50 lines)..."
    gcloud logging read \
        "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB_NAME\"" \
        --limit=50 \
        --project="$PROJECT_ID" \
        --format='value(timestamp, textPayload)' \
        2>/dev/null | tail -30 || log_info "Could not fetch logs (may need time to propagate)"

    echo ""
    log_step "Checking Neo4j node count..."
    NEO4J_COUNT=$(gcloud compute ssh "${INSTANCE_NAME}" \
        --project="${PROJECT_ID}" \
        --zone="${ZONE}" \
        --command='docker exec neo4j-staging cypher-shell -u neo4j -p ${NEO4J_PASSWORD} "MATCH (n) RETURN COUNT(n)"' \
        2>&1 | grep -oE '^[0-9]+' | head -1 || echo "unknown")

    log_info "Neo4j node count: $NEO4J_COUNT"

    echo ""
    log_step "Database queries to check:"
    echo ""
    echo "  Checkpoint statistics:"
    echo "    sqlite3 data/knowledge_base.db 'SELECT status, COUNT(*) as count FROM indexing_checkpoints GROUP BY status;'"
    echo ""
    echo "  Success rate:"
    echo "    sqlite3 data/knowledge_base.db 'SELECT ROUND(SUM(CASE WHEN status=\"indexed\" THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as success_rate FROM indexing_checkpoints;'"
    echo ""
    echo "  Error summary:"
    echo "    sqlite3 data/knowledge_base.db 'SELECT error_message, COUNT(*) FROM indexing_checkpoints WHERE status=\"failed\" GROUP BY error_message LIMIT 5;'"
fi

# Final Summary
log_section "TEST COMPLETE"

echo "Next steps:"
echo ""
if [ "$NO_WAIT" = "true" ]; then
    echo "1. Monitor job progress:"
    echo "   gcloud logging read 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB_NAME\"' --follow"
    echo ""
fi
echo "2. Verify checkpoint data:"
echo "   sqlite3 data/knowledge_base.db 'SELECT status, COUNT(*) FROM indexing_checkpoints GROUP BY status'"
echo ""
echo "3. Test resume capability (if job was interrupted):"
echo "   ./deploy/scripts/run-intake-test.sh --concurrency $CONCURRENCY --space $SPACE --resume --skip-clear"
echo ""
echo "4. Scale up concurrency (if successful):"
echo "   ./deploy/scripts/run-intake-test.sh --concurrency 5 --space $SPACE --skip-clear"
echo "   ./deploy/scripts/run-intake-test.sh --concurrency 10 --space $SPACE --skip-clear"
echo ""
echo "5. View full logs:"
echo "   gcloud logging read 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB_NAME\"' --limit=500"
echo ""
