# =============================================================================
# Backup Infrastructure
# =============================================================================
# Daily automated snapshots of production Neo4j data disk.
# Service account for backup/restore operations (used by Phase 2/3 jobs).
# =============================================================================

# -----------------------------------------------------------------------------
# Snapshot Schedule Policy - Daily at 02:00 UTC, 30-day retention
# -----------------------------------------------------------------------------
resource "google_compute_resource_policy" "neo4j_prod_snapshot" {
  name    = "neo4j-prod-daily-snapshot"
  region  = var.region
  project = var.project_id

  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = "02:00"
      }
    }

    retention_policy {
      max_retention_days    = 30
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }

    snapshot_properties {
      labels = {
        environment = "prod"
        purpose     = "neo4j-backup"
      }
      storage_locations = [var.region]
    }
  }
}

# Attach snapshot policy to production Neo4j data disk
resource "google_compute_disk_resource_policy_attachment" "neo4j_prod_snapshot" {
  name    = google_compute_resource_policy.neo4j_prod_snapshot.name
  disk    = google_compute_disk.neo4j_prod_data.name
  zone    = var.zone
  project = var.project_id
}

# -----------------------------------------------------------------------------
# Backup Operations Service Account
# -----------------------------------------------------------------------------
resource "google_service_account" "backup_ops" {
  account_id   = "backup-ops"
  display_name = "Backup Operations Service Account"
  project      = var.project_id
}

# Grant compute.admin for disk/VM operations (snapshot, create disk, attach/detach)
resource "google_project_iam_member" "backup_ops_compute" {
  project = var.project_id
  role    = "roles/compute.admin"
  member  = "serviceAccount:${google_service_account.backup_ops.email}"
}

# Grant run.invoker for Cloud Run job execution
resource "google_project_iam_member" "backup_ops_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.backup_ops.email}"
}

# =============================================================================
# Nightly Production-to-Staging Data Refresh
# =============================================================================
# Restores staging Neo4j from the latest production disk snapshot.
# Runs as a Cloud Run Job using gcloud CLI (no SSH, no VPC access needed).
# =============================================================================

# -----------------------------------------------------------------------------
# Cloud Run Job — Staging Data Refresh
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_job" "staging_data_refresh" {
  name     = "staging-data-refresh"
  location = var.region

  template {
    template {
      containers {
        image   = "gcr.io/google.com/cloudsdktool/cloud-sdk:slim"
        command = ["bash", "-c"]
        args    = [file("${path.module}/../scripts/sync-prod-to-staging.sh")]

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }

      timeout         = "1800s"
      max_retries     = 1
      service_account = google_service_account.backup_ops.email
    }
  }
}

# -----------------------------------------------------------------------------
# Cloud Scheduler — Nightly at 3 AM UTC (1 hour after snapshot)
# -----------------------------------------------------------------------------
resource "google_cloud_scheduler_job" "staging_data_refresh" {
  name        = "staging-data-refresh-nightly"
  description = "Nightly production-to-staging Neo4j data refresh via disk snapshot restore"
  schedule    = "0 3 * * *"
  time_zone   = "UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.staging_data_refresh.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  retry_config {
    retry_count = 1
  }
}
