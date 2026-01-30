# =============================================================================
# Staging Environment Infrastructure
# =============================================================================
# This file contains all staging resources for CI/CD testing.
# Staging has its own Neo4j and Slack bot - production data is never touched.
# =============================================================================

# -----------------------------------------------------------------------------
# Staging Neo4j VM (Compute Engine)
# -----------------------------------------------------------------------------
# Neo4j requires direct TCP access for Bolt protocol.
# Cloud Run cannot proxy Bolt (HTTP-only), so we use a VM like DuckDB.
# -----------------------------------------------------------------------------

resource "google_compute_instance" "neo4j_staging" {
  name         = "neo4j-staging"
  machine_type = "e2-small" # 2 vCPU, 2GB RAM - sufficient for staging
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 10
      type  = "pd-standard"
    }
  }

  # Data disk for Neo4j
  attached_disk {
    source      = google_compute_disk.neo4j_staging_data.self_link
    device_name = "neo4j-staging-data"
    mode        = "READ_WRITE"
  }

  network_interface {
    subnetwork = google_compute_subnetwork.main.self_link
    # No external IP - access via VPC only
  }

  metadata = {
    neo4j-password = random_password.neo4j_staging_password.result
  }

  metadata_startup_script = file("${path.module}/scripts/neo4j-staging-startup.sh")

  service_account {
    email  = google_service_account.neo4j_staging.email
    scopes = ["cloud-platform"]
  }

  tags = ["neo4j-staging"]

  # Allow stopping for updates
  allow_stopping_for_update = true
}

resource "google_compute_disk" "neo4j_staging_data" {
  name = "neo4j-staging-data-disk"
  type = "pd-ssd"
  zone = var.zone
  size = 20

  labels = {
    environment = "staging"
    purpose     = "neo4j-data"
  }
}

resource "google_service_account" "neo4j_staging" {
  account_id   = "neo4j-staging"
  display_name = "Neo4j Staging Service Account"
}

# Generate random password for staging Neo4j
resource "random_password" "neo4j_staging_password" {
  length  = 24
  special = false
}

# Firewall rule to allow Bolt connections from VPC
resource "google_compute_firewall" "neo4j_staging_bolt" {
  name    = "allow-neo4j-staging-bolt"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["7687"]
  }

  source_ranges = ["10.0.0.0/24", "10.8.0.0/28"] # VPC subnet + VPC connector
  target_tags   = ["neo4j-staging"]
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
        # Direct Bolt connection to VM (no TLS for internal traffic)
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
      egress    = "PRIVATE_RANGES_ONLY" # Only route private IPs through VPC
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
    google_compute_instance.neo4j_staging,
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

# -----------------------------------------------------------------------------
# Staging Secrets
# -----------------------------------------------------------------------------
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
# Staging Confluence Sync Job
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_job" "confluence_sync_staging" {
  name     = "confluence-sync-staging"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:staging"

        command = ["python", "-m", "knowledge_base.cli", "pipeline", "--spaces", "KI", "--verbose"]

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }

        # Confluence credentials (reuse production secrets)
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

        # Staging Neo4j VM
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
          # Direct Bolt connection to VM (no TLS for internal traffic)
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

        # LLM/Embeddings
        env {
          name  = "LLM_PROVIDER"
          value = "gemini"
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
          name = "ANTHROPIC_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.anthropic_api_key.secret_id
              version = "latest"
            }
          }
        }
      }

      timeout     = "14400s"  # 4 hours for full KI space intake
      max_retries = 1

      vpc_access {
        connector = google_vpc_access_connector.connector.id
        egress    = "PRIVATE_RANGES_ONLY" # Route to VM via private IP
      }

      service_account = google_service_account.slack_bot_staging.email
    }
  }

  depends_on = [
    google_compute_instance.neo4j_staging,
  ]
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
output "staging_slack_bot_url" {
  value       = google_cloud_run_v2_service.slack_bot_staging.uri
  description = "URL of the staging Slack bot Cloud Run service"
}

output "staging_neo4j_ip" {
  value       = google_compute_instance.neo4j_staging.network_interface[0].network_ip
  description = "Internal IP of the staging Neo4j VM"
}
