#!/bin/bash
# =============================================================================
# Deploy Infrastructure with Terraform
# =============================================================================
# This script initializes and applies Terraform configuration.
# =============================================================================

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/../terraform"

echo "=========================================="
echo "Deploying AI Knowledge Base to GCP"
echo "=========================================="

cd "$TERRAFORM_DIR"

# Initialize Terraform
echo ""
echo "Initializing Terraform..."
terraform init

# Validate configuration
echo ""
echo "Validating Terraform configuration..."
terraform validate

# Plan deployment
echo ""
echo "Planning deployment..."
terraform plan -out=tfplan

# Confirm before applying
echo ""
read -p "Do you want to apply this plan? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
    echo "Deployment cancelled."
    exit 0
fi

# Apply deployment
echo ""
echo "Applying deployment..."
terraform apply tfplan

# Clean up plan file
rm -f tfplan

# Get outputs
echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Outputs:"
terraform output

echo ""
echo "Next steps:"
echo "1. Run: ./deploy/scripts/add-secrets.sh (to populate secrets)"
echo "2. Configure your Slack app with the Cloud Run URL"
echo "3. Run initial Confluence sync: gcloud run jobs execute confluence-sync --region=us-central1"
