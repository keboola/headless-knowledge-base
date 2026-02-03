# =============================================================================
# Security Configuration (Cloud Armor & IAP)
# =============================================================================

# -----------------------------------------------------------------------------
# Cloud Armor (WAF & DDoS Protection)
# -----------------------------------------------------------------------------

resource "google_compute_security_policy" "edge_security" {
  name        = "kb-edge-security-policy"
  description = "WAF and DDoS protection for Knowledge Base"
  project     = var.project_id

  # Default Rule: Allow All (but logged)
  rule {
    action   = "allow"
    priority = "2147483647"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Default allow rule"
  }

  # Example: Rate Limiting (Throttle abusive IPs)
  rule {
    action   = "rate_based_ban"
    priority = "1000"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(403)"
      enforce_on_key = "IP"
      # Limit to 500 requests per minute per IP
      rate_limit_threshold {
        count        = 500
        interval_sec = 60
      }
      ban_duration_sec = 300
    }
    description = "Rate limit abusive IPs"
  }
}

# -----------------------------------------------------------------------------
# Identity-Aware Proxy (IAP) Configuration
# -----------------------------------------------------------------------------

# NOTE: The "Brand" must be created manually in the console or via gcloud alpha
# terraform can creates the client if the brand exists.

# Fetch IAP Credentials from Secret Manager
# Prerequisite: You must create these secrets manually after configuring OAuth Consent Screen

data "google_secret_manager_secret_version" "iap_client_id" {
  secret  = "iap-client-id"
  version = "latest"
  project = var.project_id
}

data "google_secret_manager_secret_version" "iap_client_secret" {
  secret  = "iap-client-secret"
  version = "latest"
  project = var.project_id
}

# -----------------------------------------------------------------------------
# IAP Permissions
# -----------------------------------------------------------------------------

resource "google_iap_web_backend_service_iam_member" "neodash_access" {
  for_each = toset(var.iap_authorized_users)
  project  = var.project_id
  web_backend_service = google_compute_backend_service.neodash_backend.name
  role     = "roles/iap.httpsResourceAccessor"
  member   = each.value
}

resource "google_iap_web_backend_service_iam_member" "neodash_staging_access" {
  for_each = toset(var.iap_authorized_users)
  project  = var.project_id
  web_backend_service = google_compute_backend_service.neodash_staging_backend.name
  role     = "roles/iap.httpsResourceAccessor"
  member   = each.value
}
