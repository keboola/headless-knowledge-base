# =============================================================================
# Staging Environment Infrastructure
# =============================================================================
# This file contains all staging resources for CI/CD testing.
# Staging has its own Neo4j and Slack bot - production data is never touched.
# =============================================================================

# -----------------------------------------------------------------------------
# Staging Neo4j
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "neo4j_staging" {
  name     = "neo4j-staging"
  location = var.region

  # Internal only - accessed via VPC by other services
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    scaling {
      min_instance_count = 0 # Scale to zero when not in use (cost saving)
      max_instance_count = 1
    }

    containers {
      image = "neo4j:5.26-community"

      ports {
        container_port = 7474
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
      }

      # Neo4j authentication
      env {
        name = "NEO4J_AUTH"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.neo4j_auth_staging.secret_id
            version = "latest"
          }
        }
      }

      # Enable APOC plugin (required by Graphiti)
      env {
        name  = "NEO4J_PLUGINS"
        value = "[\"apoc\"]"
      }

      # Allow APOC procedures
      env {
        name  = "NEO4J_dbms_security_procedures_unrestricted"
        value = "apoc.*"
      }

      # Configure Bolt connector
      env {
        name  = "NEO4J_server_bolt_listen__address"
        value = "0.0.0.0:7687"
      }

      # Configure HTTP connector
      env {
        name  = "NEO4J_server_http_listen__address"
        value = "0.0.0.0:7474"
      }

      # Disable HTTPS
      env {
        name  = "NEO4J_server_https_enabled"
        value = "false"
      }

      # Memory configuration (smaller for staging)
      env {
        name  = "NEO4J_server_memory_heap_initial__size"
        value = "256M"
      }

      env {
        name  = "NEO4J_server_memory_heap_max__size"
        value = "1G"
      }

      env {
        name  = "NEO4J_server_memory_pagecache_size"
        value = "256M"
      }

      volume_mounts {
        name       = "neo4j-data"
        mount_path = "/data"
      }

      # Note: Neo4j takes 60-90 seconds to start with GCS storage
      startup_probe {
        http_get {
          path = "/"
          port = 7474
        }
        initial_delay_seconds = 60
        period_seconds        = 10
        failure_threshold     = 30
        timeout_seconds       = 10
      }

      liveness_probe {
        http_get {
          path = "/"
          port = 7474
        }
        period_seconds    = 30
        timeout_seconds   = 5
        failure_threshold = 3
      }
    }

    volumes {
      name = "neo4j-data"
      gcs {
        bucket    = google_storage_bucket.neo4j_data_staging.name
        read_only = false
      }
    }

    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "ALL_TRAFFIC"
    }

    service_account = google_service_account.neo4j_staging.email
  }

  depends_on = [
    google_secret_manager_secret_version.neo4j_auth_staging,
  ]
}

resource "google_service_account" "neo4j_staging" {
  account_id   = "neo4j-staging"
  display_name = "Neo4j Staging Service Account"
}

resource "google_storage_bucket" "neo4j_data_staging" {
  name     = "${var.project_id}-neo4j-data-staging"
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
    purpose     = "neo4j-persistence"
  }
}

resource "google_storage_bucket_iam_member" "neo4j_staging_storage" {
  bucket = google_storage_bucket.neo4j_data_staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.neo4j_staging.email}"
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

      # Graph Database Configuration (Graphiti + Neo4j)
      env {
        name  = "GRAPH_BACKEND"
        value = "neo4j"
      }

      env {
        name  = "GRAPH_ENABLE_GRAPHITI"
        value = "true"
      }

      env {
        name  = "NEO4J_URI"
        value = "bolt+s://${replace(google_cloud_run_v2_service.neo4j_staging.uri, "https://", "")}"
      }

      env {
        name  = "NEO4J_USER"
        value = "neo4j"
      }

      env {
        name = "NEO4J_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.neo4j_password_staging.secret_id
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
    google_secret_manager_secret_version.neo4j_password_staging,
    google_cloud_run_v2_service.neo4j_staging,
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

# Allow staging bot to invoke staging Neo4j
resource "google_cloud_run_v2_service_iam_member" "neo4j_staging_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.neo4j_staging.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.slack_bot_staging.email}"
}

# -----------------------------------------------------------------------------
# Staging Secrets
# -----------------------------------------------------------------------------
resource "google_secret_manager_secret" "neo4j_auth_staging" {
  secret_id = "neo4j-auth-staging"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "neo4j_auth_staging" {
  secret      = google_secret_manager_secret.neo4j_auth_staging.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret" "neo4j_password_staging" {
  secret_id = "neo4j-password-staging"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "neo4j_password_staging" {
  secret      = google_secret_manager_secret.neo4j_password_staging.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
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
resource "google_secret_manager_secret_iam_member" "neo4j_staging_auth_access" {
  secret_id = google_secret_manager_secret.neo4j_auth_staging.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.neo4j_staging.email}"
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

resource "google_secret_manager_secret_iam_member" "slack_bot_staging_neo4j_password_access" {
  secret_id = google_secret_manager_secret.neo4j_password_staging.id
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

output "staging_neo4j_url" {
  value       = google_cloud_run_v2_service.neo4j_staging.uri
  description = "URL of the staging Neo4j Cloud Run service"
}
