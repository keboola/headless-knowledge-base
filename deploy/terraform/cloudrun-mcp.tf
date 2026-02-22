# =============================================================================
# MCP Server Cloud Run Services (Production + Staging)
# =============================================================================

# -----------------------------------------------------------------------------
# Service Account
# -----------------------------------------------------------------------------
resource "google_service_account" "mcp_server" {
  account_id   = "mcp-server"
  display_name = "MCP Server Service Account"
}

# Vertex AI access for embeddings and LLM
resource "google_project_iam_member" "mcp_server_vertex_ai" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.mcp_server.email}"
}

# -----------------------------------------------------------------------------
# Secret Manager - MCP OAuth Secrets
# -----------------------------------------------------------------------------
resource "google_secret_manager_secret" "mcp_oauth_client_id" {
  secret_id = "mcp-oauth-client-id"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "mcp"
  }
}

resource "google_secret_manager_secret_version" "mcp_oauth_client_id" {
  secret      = google_secret_manager_secret.mcp_oauth_client_id.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret" "mcp_oauth_client_secret" {
  secret_id = "mcp-oauth-client-secret"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "mcp"
  }
}

resource "google_secret_manager_secret_version" "mcp_oauth_client_secret" {
  secret      = google_secret_manager_secret.mcp_oauth_client_secret.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# IAM: MCP server SA can access OAuth secrets
resource "google_secret_manager_secret_iam_member" "mcp_oauth_client_id_access" {
  secret_id = google_secret_manager_secret.mcp_oauth_client_id.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.mcp_server.email}"
}

resource "google_secret_manager_secret_iam_member" "mcp_oauth_client_secret_access" {
  secret_id = google_secret_manager_secret.mcp_oauth_client_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.mcp_server.email}"
}

# -----------------------------------------------------------------------------
# Production MCP Server
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "mcp_server" {
  name     = "kb-mcp"
  location = var.region

  template {
    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/mcp-server:latest"

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
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

      # Neo4j connection - using internal GCE VM IP via VPC connector
      env {
        name  = "NEO4J_URI"
        value = "bolt://${google_compute_instance.neo4j_prod.network_interface[0].network_ip}:7687"
      }

      env {
        name  = "NEO4J_USER"
        value = "neo4j"
      }

      env {
        name  = "NEO4J_PASSWORD"
        value = random_password.neo4j_prod_password.result
      }

      # LLM Configuration
      env {
        name  = "LLM_PROVIDER"
        value = "gemini"
      }

      env {
        name  = "GEMINI_CONVERSATION_MODEL"
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

      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }

      # MCP OAuth Configuration
      env {
        name = "MCP_OAUTH_CLIENT_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.mcp_oauth_client_id.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "MCP_OAUTH_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.mcp_oauth_client_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "MCP_OAUTH_RESOURCE_IDENTIFIER"
        value = "https://kb-mcp.${var.base_domain}"
      }

      env {
        name  = "MCP_DEV_MODE"
        value = "false"
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

    service_account = google_service_account.mcp_server.email
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_secret_manager_secret_version.mcp_oauth_client_id,
    google_secret_manager_secret_version.mcp_oauth_client_secret,
  ]
}

# Allow unauthenticated access (OAuth is handled at application level)
resource "google_cloud_run_v2_service_iam_member" "mcp_server_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.mcp_server.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# -----------------------------------------------------------------------------
# Staging MCP Server
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "mcp_server_staging" {
  name     = "kb-mcp-staging"
  location = var.region

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/mcp-server:staging"

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
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

      # Neo4j staging connection - using internal GCE VM IP via VPC connector
      env {
        name  = "NEO4J_URI"
        value = "bolt://${google_compute_instance.neo4j_staging.network_interface[0].network_ip}:7687"
      }

      env {
        name  = "NEO4J_USER"
        value = "neo4j"
      }

      env {
        name  = "NEO4J_PASSWORD"
        value = random_password.neo4j_staging_password.result
      }

      # LLM Configuration
      env {
        name  = "LLM_PROVIDER"
        value = "gemini"
      }

      env {
        name  = "GEMINI_CONVERSATION_MODEL"
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

      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }

      # MCP OAuth Configuration (reuse same secrets for staging)
      env {
        name = "MCP_OAUTH_CLIENT_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.mcp_oauth_client_id.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "MCP_OAUTH_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.mcp_oauth_client_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "MCP_OAUTH_RESOURCE_IDENTIFIER"
        value = "https://kb-mcp-staging.${var.staging_domain}"
      }

      env {
        name  = "MCP_DEV_MODE"
        value = "false"
      }

      env {
        name  = "ENVIRONMENT"
        value = "staging"
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

    service_account = google_service_account.mcp_server.email
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_secret_manager_secret_version.mcp_oauth_client_id,
    google_secret_manager_secret_version.mcp_oauth_client_secret,
    google_compute_instance.neo4j_staging,
  ]
}

# Allow unauthenticated access (OAuth is handled at application level)
resource "google_cloud_run_v2_service_iam_member" "mcp_server_staging_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.mcp_server_staging.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
