# =============================================================================
# Neodash Web UI Service (Cloud Run)
# =============================================================================
#
# Neodash is a dashboard builder for Neo4j.
# This service is protected by Identity-Aware Proxy (IAP).
#
# =============================================================================

resource "google_cloud_run_v2_service" "neodash" {
  name     = "neodash"
  location = var.region

  # Only allow traffic from the Load Balancer
  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  depends_on = [
    google_secret_manager_secret_version.neo4j_password
  ]

  template {
    containers {
      image = "neo4jlabs/neodash:latest"

      ports {
        container_port = 5005
      }

      env {
        name  = "ssoEnabled"
        value = "true"
      }

      env {
        name  = "standalone"
        value = "true"
      }
      
      env {
        name  = "standaloneProtocol"
        value = "bolt+s"
      }

      env {
        name  = "standaloneHost"
        value = "neo4j.internal.${var.base_domain}"
      }

      env {
        name  = "standalonePort"
        value = "443"
      }

      env {
        name  = "standaloneDatabase"
        value = "neo4j"
      }

      env {
        name  = "standaloneUser"
        value = "neo4j"
      }

      env {
        name = "standalonePassword"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.neo4j_password.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "standaloneDashboardURL"
        value = "https://storage.googleapis.com/${var.project_id}-web-assets/dashboards/default.json"
      }
    }
    service_account = google_service_account.neodash.email
  }
}

# Service account for Neodash
resource "google_service_account" "neodash" {
  account_id   = "neodash-ui"
  display_name = "Neodash UI Service Account"
}

# Allow unauthenticated access to the Service itself (It is behind IAP)
# Note: Cloud Run requires this for IAP to work via Load Balancer
resource "google_cloud_run_v2_service_iam_member" "neodash_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.neodash.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
