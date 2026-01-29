# Confluence Sync Job
resource "google_cloud_run_v2_job" "confluence_sync" {
  name     = "confluence-sync"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:latest"

        command = ["python", "-m", "knowledge_base.cli", "download"]

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }

        env {
          name  = "CONFLUENCE_URL"
          value = var.confluence_base_url
        }

        env {
          name  = "CONFLUENCE_SPACE_KEYS"
          value = var.confluence_space_keys
        }

        env {
          name = "CONFLUENCE_USERNAME"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.confluence_email.secret_id
              version = "latest"
            }
          }
        }

        env {
          name = "CONFLUENCE_API_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.confluence_api_token.secret_id
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
          value = "bolt+s://${replace(google_cloud_run_v2_service.neo4j.uri, "https://", "")}"
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
          name  = "DUCKDB_HOST"
          value = google_compute_instance.duckdb.network_interface[0].network_ip
        }
      }

      timeout     = "3600s"
      max_retries = 1

      vpc_access {
        connector = google_vpc_access_connector.connector.id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      service_account = google_service_account.jobs.email
    }
  }

  depends_on = [
    google_secret_manager_secret_version.confluence_email,
    google_secret_manager_secret_version.confluence_api_token,
    google_secret_manager_secret_version.neo4j_password,
    google_cloud_run_v2_service.neo4j,
  ]
}

# Parse Job - Creates chunks from downloaded pages
resource "google_cloud_run_v2_job" "parse" {
  name     = "parse"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:latest"

        command = ["python", "-m", "knowledge_base.cli", "parse"]

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }

        env {
          name  = "DUCKDB_HOST"
          value = google_compute_instance.duckdb.network_interface[0].network_ip
        }
      }

      timeout     = "3600s"
      max_retries = 1

      vpc_access {
        connector = google_vpc_access_connector.connector.id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      service_account = google_service_account.jobs.email
    }
  }
}

# Index Rebuild Job
resource "google_cloud_run_v2_job" "index_rebuild" {
  name     = "index-rebuild"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:latest"

        command = ["python", "-m", "knowledge_base.cli", "index"]

        resources {
          limits = {
            cpu    = "4"
            memory = "4Gi"
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
          value = "bolt+s://${replace(google_cloud_run_v2_service.neo4j.uri, "https://", "")}"
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
          name  = "DUCKDB_HOST"
          value = google_compute_instance.duckdb.network_interface[0].network_ip
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
      }

      timeout     = "3600s"
      max_retries = 1

      vpc_access {
        connector = google_vpc_access_connector.connector.id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      service_account = google_service_account.jobs.email
    }
  }

  depends_on = [
    google_secret_manager_secret_version.neo4j_password,
    google_cloud_run_v2_service.neo4j,
  ]
}

# Quality Scoring Job
resource "google_cloud_run_v2_job" "quality_scoring" {
  name     = "quality-scoring"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:latest"

        command = ["python", "-m", "knowledge_base.cli", "quality-check"]

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
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
          name  = "LLM_PROVIDER"
          value = "vertex-claude"
        }

        env {
          name  = "VERTEX_AI_CLAUDE_MODEL"
          value = "claude-sonnet-4@20250514"
        }

        env {
          name  = "DUCKDB_HOST"
          value = google_compute_instance.duckdb.network_interface[0].network_ip
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
      }

      timeout     = "1800s"
      max_retries = 1

      vpc_access {
        connector = google_vpc_access_connector.connector.id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      service_account = google_service_account.jobs.email
    }
  }
}

# Metadata Generation Job
resource "google_cloud_run_v2_job" "metadata_generation" {
  name     = "metadata-generation"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:latest"

        command = ["python", "-m", "knowledge_base.cli", "metadata"]

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
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
          name  = "LLM_PROVIDER"
          value = "vertex-claude"
        }

        env {
          name  = "VERTEX_AI_CLAUDE_MODEL"
          value = "claude-sonnet-4@20250514"
        }

        env {
          name  = "DUCKDB_HOST"
          value = google_compute_instance.duckdb.network_interface[0].network_ip
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
      }

      timeout     = "3600s"
      max_retries = 1

      vpc_access {
        connector = google_vpc_access_connector.connector.id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      service_account = google_service_account.jobs.email
    }
  }
}

# Full Pipeline Job - runs download, parse, and index in sequence
resource "google_cloud_run_v2_job" "pipeline" {
  name     = "sync-pipeline"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:latest"

        command = ["python", "-m", "knowledge_base.cli", "pipeline", "--reindex"]

        resources {
          limits = {
            cpu    = "4"
            memory = "8Gi"
          }
        }

        env {
          name  = "CONFLUENCE_URL"
          value = var.confluence_base_url
        }

        env {
          name  = "CONFLUENCE_SPACE_KEYS"
          value = var.confluence_space_keys
        }

        env {
          name = "CONFLUENCE_USERNAME"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.confluence_email.secret_id
              version = "latest"
            }
          }
        }

        env {
          name = "CONFLUENCE_API_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.confluence_api_token.secret_id
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
          value = "bolt+s://${replace(google_cloud_run_v2_service.neo4j.uri, "https://", "")}"
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
          name  = "DUCKDB_HOST"
          value = google_compute_instance.duckdb.network_interface[0].network_ip
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
      }

      timeout     = "7200s" # 2 hours for full pipeline
      max_retries = 1

      vpc_access {
        connector = google_vpc_access_connector.connector.id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      service_account = google_service_account.jobs.email
    }
  }

  depends_on = [
    google_secret_manager_secret_version.confluence_email,
    google_secret_manager_secret_version.confluence_api_token,
    google_secret_manager_secret_version.neo4j_password,
    google_cloud_run_v2_service.neo4j,
  ]
}

resource "google_service_account" "jobs" {
  account_id   = "background-jobs"
  display_name = "Background Jobs Service Account"
}
