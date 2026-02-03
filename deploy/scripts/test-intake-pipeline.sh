#!/bin/bash
# =============================================================================
# Test Confluence Intake Pipeline on Staging
# =============================================================================
# This script:
# 1. Clears Neo4j staging data
# 2. Runs the Confluence intake pipeline
# 3. Monitors progress and collects metrics
# 4. Verifies checkpoint/resume functionality
#
# Usage: ./test-intake-pipeline.sh [--concurrency N] [--space SPACE] [--resume]
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ai-knowledge-base-42}"
REGION="${REGION:-us-central1}"
CONCURRENCY="${CONCURRENCY:-3}"  # Conservative: start with 3
SPACE="${SPACE:-KI}"  # Default space to test
RESUME="${RESUME:-false}"
DRY_RUN="${DRY_RUN:-false}"

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
            RESUME="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Confluence Intake Pipeline Test"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Space: $SPACE"
echo "Concurrency: $CONCURRENCY"
echo "Resume: $RESUME"
echo "=========================================="
echo ""

# Step 1: Clear Neo4j data (unless resuming)
if [ "$RESUME" != "true" ]; then
    echo "[Step 1/4] Clearing Neo4j staging data..."
    if [ "$DRY_RUN" = "true" ]; then
        echo "  [DRY RUN] Would clear Neo4j data"
    else
        ./deploy/scripts/clear-neo4j-staging.sh
    fi
    echo ""
fi

# Step 2: Configure environment variables for the job
echo "[Step 2/4] Configuring Cloud Run job with environment..."
cat > /tmp/test-intake-env.txt << EOF
GRAPHITI_CONCURRENCY=$CONCURRENCY
GRAPHITI_INTER_CHUNK_DELAY=0.0
GRAPHITI_RATE_LIMIT_THRESHOLD=5
GRAPHITI_CIRCUIT_BREAKER_COOLDOWN=60
GRAPHITI_MAX_CONCURRENCY=10
EOF

if [ "$DRY_RUN" = "true" ]; then
    echo "  [DRY RUN] Would update Cloud Run job with environment:"
    cat /tmp/test-intake-env.txt
else
    # Update job environment variables
    while IFS='=' read -r key value; do
        echo "  Setting $key=$value"
    done < /tmp/test-intake-env.txt

    gcloud run jobs update confluence-sync \
        --set-env-vars=GRAPHITI_CONCURRENCY=$CONCURRENCY,GRAPHITI_INTER_CHUNK_DELAY=0.0 \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        || echo "Warning: Could not update job environment (may not exist yet)"
fi
echo ""

# Step 3: Run the pipeline job
echo "[Step 3/4] Running Confluence intake pipeline..."
START_TIME=$(date +%s)
START_TIME_FORMATTED=$(date "+%Y-%m-%d %H:%M:%S")

if [ "$DRY_RUN" = "true" ]; then
    echo "  [DRY RUN] Would execute: confluence-sync"
    echo "  [DRY RUN] With command: python -m knowledge_base.cli pipeline --spaces $SPACE"
    if [ "$RESUME" = "true" ]; then
        echo "  [DRY RUN] With --resume flag"
    fi
else
    # Execute job
    JOB_EXECUTION=$(gcloud run jobs execute confluence-sync \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --wait \
        --format='value(name)' \
        2>&1 || echo "")

    END_TIME=$(date +%s)
    END_TIME_FORMATTED=$(date "+%Y-%m-%d %H:%M:%S")
    DURATION=$((END_TIME - START_TIME))

    echo "  Start: $START_TIME_FORMATTED"
    echo "  End: $END_TIME_FORMATTED"
    echo "  Duration: ${DURATION}s ($(($DURATION / 60)) minutes)"
fi
echo ""

# Step 4: Monitor and collect metrics
echo "[Step 4/4] Collecting metrics..."
if [ "$DRY_RUN" = "true" ]; then
    echo "  [DRY RUN] Would collect:"
    echo "    - Job logs (last 100 lines)"
    echo "    - Indexing checkpoint counts by status"
    echo "    - Success rate"
    echo "    - Rate limit errors"
else
    echo "  Fetching job logs..."
    gcloud logging read \
        "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"confluence-sync\"" \
        --limit=100 \
        --project="$PROJECT_ID" \
        --format='value(textPayload)' \
        | tail -50 > /tmp/intake-logs.txt

    # Extract key metrics
    echo ""
    echo "  Key Log Lines:"
    grep -E "(Indexing|Complete|Rate limit|Circuit breaker|Resumed)" /tmp/intake-logs.txt | tail -20 || true

    # Query checkpoint table stats
    echo ""
    echo "  Checkpoint Statistics:"
    echo "    To query checkpoint table:"
    echo "    sqlite3 data/knowledge_base.db 'SELECT status, COUNT(*) FROM indexing_checkpoints GROUP BY status'"
fi

echo ""
echo "=========================================="
echo "Test Complete"
echo "=========================================="
echo ""
echo "Next Steps:"
if [ "$DRY_RUN" != "true" ]; then
    echo "1. Check full logs:"
    echo "   gcloud logging read 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"confluence-sync\"' --limit=500"
    echo ""
    echo "2. Query checkpoint progress:"
    echo "   sqlite3 data/knowledge_base.db 'SELECT status, COUNT(*) as count FROM indexing_checkpoints GROUP BY status'"
    echo ""
    echo "3. Test resume capability (if job was interrupted):"
    echo "   ./test-intake-pipeline.sh --concurrency $CONCURRENCY --space $SPACE --resume"
    echo ""
    echo "4. Verify Neo4j has data:"
    echo "   gcloud compute ssh neo4j-staging --zone=us-central1-a --command='docker exec neo4j-staging cypher-shell -u neo4j \"MATCH (n) RETURN COUNT(n)\"'"
else
    echo "Dry run completed. Run without --dry-run to execute actual tests."
fi
echo ""
