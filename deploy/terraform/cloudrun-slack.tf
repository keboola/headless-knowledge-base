# Slack Bot Cloud Run Service
resource "google_cloud_run_v2_service" "slack_bot" {
  name     = "slack-bot"
  location = var.region

  template {
    scaling {
      min_instance_count = 1
      max_instance_count = 10
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/slack-bot:latest"

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
            secret  = google_secret_manager_secret.slack_bot_token.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "SLACK_SIGNING_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_signing_secret.secret_id
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
        value = replace(google_cloud_run_v2_service.chromadb.uri, "https://", "")
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
            secret  = google_secret_manager_secret.chromadb_token.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "DUCKDB_HOST"
        value = google_compute_instance.duckdb.network_interface[0].network_ip
      }

      env {
        name  = "LLM_PROVIDER"
        value = "vertex-claude"
      }

      env {
        name  = "VERTEX_AI_CLAUDE_MODEL"
        value = "claude-3-5-sonnet-v2@20241022"
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

      # Health check
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

    service_account = google_service_account.slack_bot.email
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_secret_manager_secret_version.slack_bot_token,
    google_secret_manager_secret_version.slack_signing_secret,
    google_secret_manager_secret_version.anthropic_api_key,
  ]
}

# Allow unauthenticated access (Slack needs to reach the endpoint)
resource "google_cloud_run_v2_service_iam_member" "slack_bot_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.slack_bot.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_service_account" "slack_bot" {
  account_id   = "slack-bot"
  display_name = "Slack Bot Service Account"
}
