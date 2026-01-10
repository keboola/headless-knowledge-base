#!/bin/bash
# =============================================================================
# Run Cloud Run Job
# =============================================================================
# This script triggers a Cloud Run job manually.
# Usage: ./run-job.sh <job-name>
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ai-knowledge-base-42}"
REGION="${REGION:-us-central1}"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <job-name>"
    echo ""
    echo "Available jobs:"
    echo "  - confluence-sync      Sync documents from Confluence"
    echo "  - metadata-generation  Generate metadata for documents"
    echo "  - index-rebuild        Rebuild vector index"
    echo "  - quality-scoring      Update quality scores"
    exit 1
fi

JOB_NAME=$1

echo "=========================================="
echo "Running Cloud Run Job: $JOB_NAME"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "=========================================="

# Execute the job
gcloud run jobs execute "$JOB_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --wait

echo ""
echo "Job execution complete."
echo ""
echo "To view logs:"
echo "  gcloud logging read 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB_NAME\"' --limit=100"
