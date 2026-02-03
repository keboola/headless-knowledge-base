# Cloud Scheduler Service Account
resource "google_service_account" "scheduler" {
  account_id   = "scheduler"
  display_name = "Cloud Scheduler Service Account"
}

# Grant scheduler permission to invoke Cloud Run jobs
resource "google_project_iam_member" "scheduler_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

# Daily Confluence Sync - 2 AM UTC
resource "google_cloud_scheduler_job" "confluence_sync" {
  name        = "confluence-sync-daily"
  description = "Daily Confluence synchronization"
  schedule    = "0 2 * * *"
  time_zone   = "UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.confluence_sync.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  retry_config {
    retry_count = 1
  }
}

# Daily Parse - 2:30 AM UTC (after Confluence sync)
resource "google_cloud_scheduler_job" "parse" {
  name        = "parse-daily"
  description = "Daily parsing of downloaded pages into chunks"
  schedule    = "30 2 * * *"
  time_zone   = "UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.parse.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  retry_config {
    retry_count = 1
  }
}

# Daily Metadata Generation - 3 AM UTC (after parse)
resource "google_cloud_scheduler_job" "metadata_generation" {
  name        = "metadata-generation-daily"
  description = "Daily metadata generation for new documents"
  schedule    = "0 3 * * *"
  time_zone   = "UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.metadata_generation.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  retry_config {
    retry_count = 1
  }
}

# Weekly Index Rebuild - Sunday 4 AM UTC
resource "google_cloud_scheduler_job" "index_rebuild" {
  name        = "index-rebuild-weekly"
  description = "Weekly vector index rebuild"
  schedule    = "0 4 * * 0"
  time_zone   = "UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.index_rebuild.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  retry_config {
    retry_count = 1
  }
}

# Daily Quality Scoring - 5 AM UTC
resource "google_cloud_scheduler_job" "quality_scoring" {
  name        = "quality-scoring-daily"
  description = "Daily quality score updates"
  schedule    = "0 5 * * *"
  time_zone   = "UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.quality_scoring.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  retry_config {
    retry_count = 1
  }
}

# Daily Full Pipeline - 2 AM UTC (replaces separate sync/parse/index jobs)
resource "google_cloud_scheduler_job" "pipeline" {
  name        = "sync-pipeline-daily"
  description = "Daily full sync pipeline: download -> parse -> index"
  schedule    = "0 2 * * *"
  time_zone   = "UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.pipeline.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  retry_config {
    retry_count = 1
  }
}
