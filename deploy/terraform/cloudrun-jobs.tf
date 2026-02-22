# =============================================================================
# Pipeline State Storage (GCS bucket for SQLite DB persistence across job runs)
# =============================================================================

resource "google_storage_bucket" "pipeline_state" {
  name                        = "${var.project_id}-pipeline-state"
  location                    = var.region
  project                     = var.project_id
  uniform_bucket_level_access = true

  versioning {
    enabled = true # Protect against accidental overwrites
  }
}

# IAM: production jobs SA can read/write pipeline state
resource "google_storage_bucket_iam_member" "jobs_pipeline_state" {
  bucket = google_storage_bucket.pipeline_state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.jobs.email}"
}

# =============================================================================
# Full Pipeline Job - runs download, parse, and index in sequence
# =============================================================================

resource "google_cloud_run_v2_job" "pipeline" {
  provider = google-beta
  name     = "sync-pipeline"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:latest"

        # Shell wrapper: restore SQLite DB from GCS FUSE mount at start.
        # The app continuously persists checkpoints via CHECKPOINT_PERSIST_PATH.
        command = ["/bin/sh", "-c"]
        args = [
          "cp /mnt/pipeline-state/prod-knowledge-base.db ./knowledge_base.db 2>/dev/null && echo 'Restored checkpoint DB from persistent storage' || echo 'No checkpoint DB found, starting fresh'; python -m knowledge_base.cli pipeline"
        ]

        resources {
          limits = {
            cpu    = "4"
            memory = "8Gi"
          }
        }

        volume_mounts {
          name       = "pipeline-state"
          mount_path = "/mnt/pipeline-state"
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

        # LLM for Graphiti (matches staging config)
        env {
          name  = "LLM_PROVIDER"
          value = "gemini"
        }

        env {
          name  = "GOOGLE_GENAI_USE_VERTEXAI"
          value = "true"
        }

        env {
          name  = "GEMINI_INTAKE_MODEL"
          value = "gemini-2.5-flash"
        }

        env {
          name  = "GRAPHITI_BULK_ENABLED"
          value = "true"
        }

        env {
          name  = "CHECKPOINT_PERSIST_PATH"
          value = "/mnt/pipeline-state/prod-knowledge-base.db"
        }
      }

      volumes {
        name = "pipeline-state"
        gcs {
          bucket    = google_storage_bucket.pipeline_state.name
          read_only = false
        }
      }

      execution_environment = "EXECUTION_ENVIRONMENT_GEN2" # Required for GCS FUSE volumes

      timeout     = "86400s" # 24 hours — Graphiti indexing is slow due to LLM calls per chunk
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
  ]
}

resource "google_service_account" "jobs" {
  account_id   = "background-jobs"
  display_name = "Background Jobs Service Account"
}
