# =============================================================================
# Staging Environment Infrastructure
# =============================================================================
# This file contains all staging resources for CI/CD testing.
# Staging has its own ChromaDB and Slack bot - production data is never touched.
# =============================================================================

# -----------------------------------------------------------------------------
# Staging ChromaDB
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "chromadb_staging" {
  name     = "chromadb-staging"
  location = var.region

  template {
    scaling {
      min_instance_count = 0 # Scale to zero when not in use (cost saving)
      max_instance_count = 2
    }

    containers {
      image = "chromadb/chroma:latest"

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
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
            secret  = google_secret_manager_secret.chromadb_token_staging.secret_id
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
        bucket    = google_storage_bucket.chromadb_data_staging.name
        read_only = false
      }
    }

    service_account = google_service_account.chromadb_staging.email
  }

  depends_on = [
    google_secret_manager_secret_version.chromadb_token_staging,
  ]
}

resource "google_service_account" "chromadb_staging" {
  account_id   = "chromadb-staging"
  display_name = "ChromaDB Staging Service Account"
}

resource "google_storage_bucket" "chromadb_data_staging" {
  name     = "${var.project_id}-chromadb-data-staging"
  location = var.region

  uniform_bucket_level_access = true

  # Auto-delete old data after 30 days (staging doesn't need long retention)
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment = "staging"
    purpose     = "chromadb-persistence"
  }
}

resource "google_storage_bucket_iam_member" "chromadb_staging_storage" {
  bucket = google_storage_bucket.chromadb_data_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.chromadb_staging.email}"
}

# -----------------------------------------------------------------------------
# Staging Slack Bot
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "slack_bot_staging" {
  name     = "slack-bot-staging"
  location = var.region

  template {
    scaling {
      min_instance_count = 0 # Scale to zero when not in use
      max_instance_count = 2
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/slack-bot:staging"

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name = "SLACK_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_bot_token_staging.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "SLACK_SIGNING_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_signing_secret_staging.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "ANTHROPIC_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.anthropic_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "CHROMA_HOST"
        value = replace(google_cloud_run_v2_service.chromadb_staging.uri, "https://", "")
      }

      env {
        name  = "CHROMA_PORT"
        value = "443"
      }

      env {
        name  = "CHROMA_USE_SSL"
        value = "true"
      }

      env {
        name = "CHROMA_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.chromadb_token_staging.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "DUCKDB_HOST"
        value = "" # Empty - use local ephemeral DuckDB in staging
      }

      env {
        name  = "LLM_PROVIDER"
        value = "gemini"
      }

      env {
        name  = "GEMINI_MODEL_ID"
        value = "gemini-2.0-flash"
      }

      env {
        name  = "EMBEDDING_PROVIDER"
        value = "vertex-ai"
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "VERTEX_AI_PROJECT"
        value = var.project_id
      }

      env {
        name  = "VERTEX_AI_LOCATION"
        value = var.region
      }

      env {
        name  = "ENVIRONMENT"
        value = "staging"
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 3
      }
    }

    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    service_account = google_service_account.slack_bot_staging.email
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_secret_manager_secret_version.slack_bot_token_staging,
    google_secret_manager_secret_version.slack_signing_secret_staging,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "slack_bot_staging_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.slack_bot_staging.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_service_account" "slack_bot_staging" {
  account_id   = "slack-bot-staging"
  display_name = "Slack Bot Staging Service Account"
}

# Allow staging bot to invoke staging ChromaDB
resource "google_cloud_run_v2_service_iam_member" "chromadb_staging_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.chromadb_staging.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.slack_bot_staging.email}"
}

# -----------------------------------------------------------------------------
# Staging Secrets
# -----------------------------------------------------------------------------
resource "google_secret_manager_secret" "chromadb_token_staging" {
  secret_id = "chromadb-token-staging"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "chromadb_token_staging" {
  secret      = google_secret_manager_secret.chromadb_token_staging.id
  secret_data = var.chromadb_token_staging
}

resource "google_secret_manager_secret" "slack_bot_token_staging" {
  secret_id = "slack-bot-token-staging"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "slack_bot_token_staging" {
  secret      = google_secret_manager_secret.slack_bot_token_staging.id
  secret_data = var.slack_bot_token_staging
}

resource "google_secret_manager_secret" "slack_signing_secret_staging" {
  secret_id = "slack-signing-secret-staging"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "slack_signing_secret_staging" {
  secret      = google_secret_manager_secret.slack_signing_secret_staging.id
  secret_data = var.slack_signing_secret_staging
}

# Grant staging service accounts access to secrets
resource "google_secret_manager_secret_iam_member" "chromadb_staging_token_access" {
  secret_id = google_secret_manager_secret.chromadb_token_staging.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.chromadb_staging.email}"
}

resource "google_secret_manager_secret_iam_member" "slack_bot_staging_token_access" {
  secret_id = google_secret_manager_secret.slack_bot_token_staging.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.slack_bot_staging.email}"
}

resource "google_secret_manager_secret_iam_member" "slack_bot_staging_signing_access" {
  secret_id = google_secret_manager_secret.slack_signing_secret_staging.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.slack_bot_staging.email}"
}

resource "google_secret_manager_secret_iam_member" "slack_bot_staging_chroma_token_access" {
  secret_id = google_secret_manager_secret.chromadb_token_staging.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.slack_bot_staging.email}"
}

resource "google_secret_manager_secret_iam_member" "slack_bot_staging_anthropic_access" {
  secret_id = google_secret_manager_secret.anthropic_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.slack_bot_staging.email}"
}

# Grant Vertex AI permissions to staging bot for embeddings
resource "google_project_iam_member" "slack_bot_staging_vertex_ai" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.slack_bot_staging.email}"
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
output "staging_slack_bot_url" {
  value       = google_cloud_run_v2_service.slack_bot_staging.uri
  description = "URL of the staging Slack bot Cloud Run service"
}

output "staging_chromadb_url" {
  value       = google_cloud_run_v2_service.chromadb_staging.uri
  description = "URL of the staging ChromaDB Cloud Run service"
}
