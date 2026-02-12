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

      # Graph Database Configuration (Graphiti + Neo4j)
      env {
        name  = "GRAPH_BACKEND"
        value = "neo4j"
      }

      env {
        name  = "GRAPH_ENABLE_GRAPHITI"
        value = "true"
      }

      # Neo4j connection - using internal Cloud Run URL
      # Note: Bolt protocol over HTTPS via Cloud Run's internal networking
      # Cloud Run exposes services on port 443, so we need bolt+s://...:443
      env {
        name  = "NEO4J_URI"
        value = "bolt+s://${replace(google_cloud_run_v2_service.neo4j.uri, "https://", "")}:443"
      }

      env {
        name  = "NEO4J_USER"
        value = "neo4j"
      }

      env {
        name = "NEO4J_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.neo4j_password.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "LLM_PROVIDER"
        value = "gemini"
      }

      env {
        name  = "GEMINI_MODEL_ID"
        value = "gemini-2.5-flash"
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
    google_secret_manager_secret_version.neo4j_password,
    google_cloud_run_v2_service.neo4j,
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
