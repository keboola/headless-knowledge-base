#!/bin/bash
# =============================================================================
# GCP Initial Setup Script
# =============================================================================
# This script enables required APIs and creates initial resources.
# Run this once before running Terraform.
# =============================================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ai-knowledge-base-42}"
REGION="${REGION:-us-central1}"

echo "=========================================="
echo "Setting up GCP project: $PROJECT_ID"
echo "Region: $REGION"
echo "=========================================="

# Set project
echo "Setting active project..."
gcloud config set project $PROJECT_ID

# Enable required APIs
echo ""
echo "Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  compute.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  vpcaccess.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com

echo "APIs enabled successfully."

# Create Artifact Registry repository
echo ""
echo "Creating Artifact Registry repository..."
gcloud artifacts repositories create knowledge-base \
  --repository-format=docker \
  --location=$REGION \
  --description="Knowledge Base Docker images" \
  2>/dev/null || echo "Repository already exists, skipping."

# Create Terraform state bucket
TFSTATE_BUCKET="${PROJECT_ID}-tfstate"
echo ""
echo "Creating Terraform state bucket: gs://$TFSTATE_BUCKET"
gsutil mb -p $PROJECT_ID -l $REGION gs://${TFSTATE_BUCKET} 2>/dev/null || echo "Bucket already exists, skipping."
gsutil versioning set on gs://${TFSTATE_BUCKET}

# Create default network if it doesn't exist
echo ""
echo "Checking VPC network..."
if ! gcloud compute networks describe default --project=$PROJECT_ID &>/dev/null; then
    echo "Default network not found. The Terraform config will create the VPC."
fi

echo ""
echo "=========================================="
echo "GCP setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Copy deploy/terraform/terraform.tfvars.example to deploy/terraform/terraform.tfvars"
echo "2. Edit terraform.tfvars with your configuration"
echo "3. Run: ./deploy/scripts/build-push.sh"
echo "4. Run: ./deploy/scripts/deploy.sh"
echo "5. Run: ./deploy/scripts/add-secrets.sh"
