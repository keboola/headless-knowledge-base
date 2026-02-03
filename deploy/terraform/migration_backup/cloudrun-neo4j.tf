# =============================================================================
# Neo4j Graph Database Service (Cloud Run)
# =============================================================================
#
# Neo4j is used by Graphiti for knowledge graph storage.
# This deployment uses Cloud Run with GCS for persistence.
#
# IMPORTANT NOTES:
# - min_instance_count=1 keeps the instance warm for low latency
# - max_instance_count=1 ensures data consistency (single writer)
# - GCS volume mounting may have limitations with Neo4j's file locking
# - If issues occur, consider migrating to GCE with persistent SSD (like DuckDB)
#
# =============================================================================

resource "google_cloud_run_v2_service" "neo4j" {
  name     = "neo4j"
  location = var.region

  # Allow access only via Load Balancer (or VPC)
  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    scaling {
      min_instance_count = 1 # Keep warm for quick responses
      max_instance_count = 1 # Single instance for data consistency
    }

    containers {
      image = "neo4j:5.26-community"

      # HTTP port for WebSocket connections (GCLB/Cloud Run compatible)
      ports {
        container_port = 7474
        name           = "h2c"
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
      }

      # Neo4j authentication
      env {
        name = "NEO4J_AUTH"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.neo4j_auth.secret_id
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

      # Configure HTTP connector to listen on all interfaces
      env {
        name  = "NEO4J_server_http_listen__address"
        value = "0.0.0.0:7474"
      }

      # Allow all origins for WebSocket connections
      env {
        name  = "NEO4J_server_http_allowed__origins"
        value = "*:*"
      }

      # Disable HTTPS (using Cloud Run's TLS termination)
      env {
        name  = "NEO4J_server_https_enabled"
        value = "false"
      }

      # Memory configuration
      env {
        name  = "NEO4J_server_memory_heap_initial__size"
        value = "1G"
      }

      env {
        name  = "NEO4J_server_memory_heap_max__size"
        value = "2G"
      }

      env {
        name  = "NEO4J_server_memory_pagecache_size"
        value = "512M"
      }

      volume_mounts {
        name       = "neo4j-data"
        mount_path = "/data"
      }

      # Startup probe on HTTP port
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
    }

    volumes {
      name = "neo4j-data"
      gcs {
        bucket    = google_storage_bucket.neo4j_data.name
        read_only = false
      }
    }

    # VPC access for internal communication
    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "ALL_TRAFFIC"
    }

    service_account = google_service_account.neo4j.email
  }

  depends_on = [
    google_secret_manager_secret_version.neo4j_auth,
    google_storage_bucket.neo4j_data,
  ]
}

# GCS bucket for Neo4j data persistence
resource "google_storage_bucket" "neo4j_data" {
  name     = "${var.project_id}-neo4j-data"
  location = var.region

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  labels = {
    environment = var.environment
    purpose     = "neo4j-persistence"
  }
}

# Service account for Neo4j
resource "google_service_account" "neo4j" {
  account_id   = "neo4j-graph"
  display_name = "Neo4j Graph Database Service Account"
}

# Grant Neo4j service account access to its storage bucket
resource "google_storage_bucket_iam_member" "neo4j_storage" {
  bucket = google_storage_bucket.neo4j_data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.neo4j.email}"
}

# Allow Slack bot to invoke Neo4j service
resource "google_cloud_run_v2_service_iam_member" "neo4j_slack_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.neo4j.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.slack_bot.email}"
}

# Allow background jobs to invoke Neo4j service
resource "google_cloud_run_v2_service_iam_member" "neo4j_jobs_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.neo4j.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.jobs.email}"
}
# Allow unauthenticated access to Neo4j service (It is behind Cloud Armor)
resource "google_cloud_run_v2_service_iam_member" "neo4j_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.neo4j.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
