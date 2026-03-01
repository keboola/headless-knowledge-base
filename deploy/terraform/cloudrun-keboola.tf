# =============================================================================
# Keboola Sync Cloud Run Job
# =============================================================================

variable "keboola_api_url" {
  description = "Keboola Storage API base URL"
  type        = string
  default     = "https://connection.us-east4.gcp.keboola.com"
}

variable "keboola_table_id" {
  description = "Keboola Storage table ID for Confluence embeddings"
  type        = string
  default     = "in.c-keboola-app-embeddings-v2-1226905101.confluence-embeddings-chunked"
}

# -----------------------------------------------------------------------------
# Secret Manager - Keboola API credentials
# -----------------------------------------------------------------------------
resource "google_secret_manager_secret" "keboola_api_token" {
  secret_id = "keboola-api-token"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "keboola"
  }
}

# Secret value is managed out-of-band via:
#   gcloud secrets versions add keboola-api-token --data-file=- --project=ai-knowledge-base-42
# The lifecycle block prevents Terraform from overwriting the real value.
resource "google_secret_manager_secret_version" "keboola_api_token" {
  secret      = google_secret_manager_secret.keboola_api_token.id
  secret_data = "PLACEHOLDER_UPDATE_VIA_GCLOUD"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# IAM: jobs SA can access Keboola secret
resource "google_secret_manager_secret_iam_member" "jobs_keboola_token_access" {
  secret_id = google_secret_manager_secret.keboola_api_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.jobs.email}"
}

# -----------------------------------------------------------------------------
# Cloud Run Job - Keboola Sync
# -----------------------------------------------------------------------------
resource "google_cloud_run_v2_job" "keboola_sync" {
  provider = google-beta
  name     = "keboola-sync"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:latest"

        # Restore checkpoint DB then run keboola-sync
        command = ["/bin/sh", "-c"]
        args = [
          "cp /mnt/pipeline-state/prod-knowledge-base.db ./knowledge_base.db 2>/dev/null && echo 'Restored checkpoint DB from persistent storage' || echo 'No checkpoint DB found, starting fresh'; python -m knowledge_base.cli keboola-sync --verbose"
        ]

        resources {
          limits = {
            cpu    = "2"
            memory = "4Gi"
          }
        }

        volume_mounts {
          name       = "pipeline-state"
          mount_path = "/mnt/pipeline-state"
        }

        # Keboola credentials
        env {
          name = "KEBOOLA_API_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.keboola_api_token.secret_id
              version = "latest"
            }
          }
        }

        env {
          name  = "KEBOOLA_API_URL"
          value = var.keboola_api_url
        }

        env {
          name  = "KEBOOLA_TABLE_ID"
          value = var.keboola_table_id
        }

        # Graph Database Configuration
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
          name = "NEO4J_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.neo4j_password.secret_id
              version = "latest"
            }
          }
        }

        # LLM - Graphiti requires 16384 max output tokens; gemini-2.0-flash-lite
        # and gemini-2.0-flash only support 8192, so gemini-2.5-flash is needed.
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

        # Embeddings
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

        # Checkpoint persistence
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

      execution_environment = "EXECUTION_ENVIRONMENT_GEN2" # Required for GCS FUSE

      timeout     = "86400s" # 24 hours - Graphiti indexing is slow
      max_retries = 1

      vpc_access {
        connector = google_vpc_access_connector.connector.id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      service_account = google_service_account.jobs.email
    }
  }

  depends_on = [
    google_secret_manager_secret_version.keboola_api_token,
    google_secret_manager_secret_version.neo4j_password,
  ]
}

# =============================================================================
# Keboola Batch Import Cloud Run Job
# =============================================================================
# Runs the full batch import pipeline: download from Keboola -> Gemini Batch API
# entity extraction -> entity resolution -> embedding -> Neo4j bulk load.
# Needs 4 CPU / 8Gi to hold ~44K chunks + extracted entities in memory.

variable "batch_gcs_prefix" {
  description = "GCS path prefix for batch import JSONL files and state"
  type        = string
  default     = "batch-import"
}

variable "batch_gemini_model" {
  description = "Gemini model for batch entity extraction"
  type        = string
  default     = "gemini-2.5-flash"
}

resource "google_cloud_run_v2_job" "keboola_batch_import" {
  provider = google-beta
  name     = "keboola-batch-import"
  location = var.region

  template {
    template {
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/knowledge-base/jobs:latest"

        # Restore checkpoint DB then run batch import
        command = ["/bin/sh", "-c"]
        args = [
          "cp /mnt/pipeline-state/prod-knowledge-base.db ./knowledge_base.db 2>/dev/null && echo 'Restored checkpoint DB from persistent storage' || echo 'No checkpoint DB found, starting fresh'; python -m knowledge_base.cli keboola-batch-import --verbose"
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

        # Keboola credentials
        env {
          name = "KEBOOLA_API_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.keboola_api_token.secret_id
              version = "latest"
            }
          }
        }

        env {
          name  = "KEBOOLA_API_URL"
          value = var.keboola_api_url
        }

        env {
          name  = "KEBOOLA_TABLE_ID"
          value = var.keboola_table_id
        }

        # Graph Database Configuration
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
          name = "NEO4J_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.neo4j_password.secret_id
              version = "latest"
            }
          }
        }

        # LLM Configuration
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

        # Embeddings
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

        # Checkpoint persistence
        env {
          name  = "CHECKPOINT_PERSIST_PATH"
          value = "/mnt/pipeline-state/prod-knowledge-base.db"
        }

        # Batch Import Pipeline settings
        env {
          name  = "BATCH_GCS_BUCKET"
          value = google_storage_bucket.pipeline_state.name
        }

        env {
          name  = "BATCH_GEMINI_MODEL"
          value = var.batch_gemini_model
        }

        env {
          name  = "BATCH_GCS_PREFIX"
          value = var.batch_gcs_prefix
        }
      }

      volumes {
        name = "pipeline-state"
        gcs {
          bucket    = google_storage_bucket.pipeline_state.name
          read_only = false
        }
      }

      execution_environment = "EXECUTION_ENVIRONMENT_GEN2" # Required for GCS FUSE

      timeout     = "86400s" # 24 hours - batch extraction + embedding + Neo4j load
      max_retries = 0        # Batch jobs should not auto-retry

      vpc_access {
        connector = google_vpc_access_connector.connector.id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      service_account = google_service_account.jobs.email
    }
  }

  depends_on = [
    google_secret_manager_secret_version.keboola_api_token,
    google_secret_manager_secret_version.neo4j_password,
  ]
}
