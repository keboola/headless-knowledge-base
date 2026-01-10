# =============================================================================
# AI Knowledge Base - GCP Infrastructure
# =============================================================================
#
# This Terraform configuration deploys the AI Knowledge Base to GCP.
#
# Components:
# - VPC Network with private subnets
# - GCE instance for DuckDB (stateful database)
# - Cloud Run service for Slack bot
# - Cloud Run service for ChromaDB
# - Cloud Run Jobs for background tasks
# - Cloud Scheduler for automated job triggers
# - Secret Manager for sensitive data
# - Cloud Storage for ChromaDB persistence
#
# Usage:
#   1. terraform init
#   2. terraform plan
#   3. terraform apply
#
# =============================================================================

# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "run.googleapis.com",
    "compute.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "vpcaccess.googleapis.com",
    "cloudbuild.googleapis.com",
    "storage.googleapis.com",
    "aiplatform.googleapis.com",
  ])

  project = var.project_id
  service = each.value

  disable_on_destroy = false
}

# Artifact Registry for Docker images
resource "google_artifact_registry_repository" "knowledge_base" {
  location      = var.region
  repository_id = "knowledge-base"
  description   = "Docker images for AI Knowledge Base"
  format        = "DOCKER"

  labels = {
    environment = var.environment
  }

  depends_on = [google_project_service.required_apis]
}
