# ChromaDB Cloud Run Service
resource "google_cloud_run_v2_service" "chromadb" {
  name     = "chromadb"
  location = var.region

  template {
    scaling {
      min_instance_count = 1 # Keep warm for quick responses
      max_instance_count = 3
    }

    containers {
      image = "chromadb/chroma:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      ports {
        container_port = 8000
      }

      env {
        name  = "CHROMA_SERVER_AUTHN_PROVIDER"
        value = "chromadb.auth.token_authn.TokenAuthenticationServerProvider"
      }

      env {
        name = "CHROMA_SERVER_AUTHN_CREDENTIALS"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.chromadb_token.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "PERSIST_DIRECTORY"
        value = "/chroma/data"
      }

      env {
        name  = "IS_PERSISTENT"
        value = "TRUE"
      }

      volume_mounts {
        name       = "chroma-data"
        mount_path = "/chroma/data"
      }

      # Health check - using v2 API (v1 is deprecated)
      startup_probe {
        http_get {
          path = "/api/v2/heartbeat"
          port = 8000
        }
        initial_delay_seconds = 10
        period_seconds        = 10
        failure_threshold     = 5
      }

      liveness_probe {
        http_get {
          path = "/api/v2/heartbeat"
          port = 8000
        }
        period_seconds = 30
      }
    }

    volumes {
      name = "chroma-data"
      gcs {
        bucket    = google_storage_bucket.chromadb_data.name
        read_only = false
      }
    }

    service_account = google_service_account.chromadb.email
  }

  depends_on = [
    google_secret_manager_secret_version.chromadb_token,
  ]
}

# Internal only - restrict access to specific service accounts
resource "google_cloud_run_v2_service_iam_member" "chromadb_slack_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.chromadb.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.slack_bot.email}"
}

resource "google_cloud_run_v2_service_iam_member" "chromadb_jobs_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.chromadb.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.jobs.email}"
}

resource "google_service_account" "chromadb" {
  account_id   = "chromadb"
  display_name = "ChromaDB Service Account"
}

resource "google_storage_bucket" "chromadb_data" {
  name     = "${var.project_id}-chromadb-data"
  location = var.region

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  labels = {
    environment = var.environment
    purpose     = "chromadb-persistence"
  }
}

# Grant ChromaDB service account access to its storage bucket
resource "google_storage_bucket_iam_member" "chromadb_storage" {
  bucket = google_storage_bucket.chromadb_data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.chromadb.email}"
}
