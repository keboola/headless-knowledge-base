# =============================================================================
# Global External HTTP(S) Load Balancer
# =============================================================================

# Global Static IP
resource "google_compute_global_address" "lb_ip" {
  name    = "kb-load-balancer-ip"
  project = var.project_id
}

# Managed SSL Certificate (UI Only)
resource "google_compute_managed_ssl_certificate" "cert_v3" {
  name    = "kb-managed-cert-v3-ui" # Renaming to force replace
  project = var.project_id

  managed {
    domains = [
      "kb.internal.${var.base_domain}",
      "kb.staging.${var.staging_domain}"
    ]
  }

  lifecycle {
    create_before_destroy = true
  }
}

# -----------------------------------------------------------------------------
# Serverless NEGs (Network Endpoint Groups)
# -----------------------------------------------------------------------------

resource "google_compute_region_network_endpoint_group" "neodash_neg" {
  name                  = "neodash-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id
  cloud_run {
    service = google_cloud_run_v2_service.neodash.name
  }
}

resource "google_compute_region_network_endpoint_group" "neodash_staging_neg" {
  name                  = "neodash-staging-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id
  cloud_run {
    service = google_cloud_run_v2_service.neodash_staging.name
  }
}

# -----------------------------------------------------------------------------
# Backend Services
# -----------------------------------------------------------------------------

# Neodash Backend (Protected by IAP)
resource "google_compute_backend_service" "neodash_backend" {
  name        = "neodash-backend"
  protocol    = "HTTPS"
  port_name   = "http"
  timeout_sec = 30
  enable_cdn  = false # CDN and IAP cannot both be enabled
  project     = var.project_id

  backend {
    group = google_compute_region_network_endpoint_group.neodash_neg.id
  }

  iap {
    oauth2_client_id     = data.google_secret_manager_secret_version.iap_client_id.secret_data
    oauth2_client_secret = data.google_secret_manager_secret_version.iap_client_secret.secret_data
  }
}

resource "google_compute_backend_service" "neodash_staging_backend" {
  name        = "neodash-staging-backend"
  protocol    = "HTTPS"
  port_name   = "http"
  timeout_sec = 30
  enable_cdn  = false # CDN and IAP cannot both be enabled
  project     = var.project_id

  backend {
    group = google_compute_region_network_endpoint_group.neodash_staging_neg.id
  }

  iap {
    oauth2_client_id     = data.google_secret_manager_secret_version.iap_client_id.secret_data
    oauth2_client_secret = data.google_secret_manager_secret_version.iap_client_secret.secret_data
  }
}

# -----------------------------------------------------------------------------
# URL Map & Routing (UI Only)
# -----------------------------------------------------------------------------

resource "google_compute_url_map" "default" {
  name    = "kb-url-map"
  project = var.project_id

  default_service = google_compute_backend_service.neodash_backend.id

  # Production UI
  host_rule {
    hosts        = ["kb.internal.${var.base_domain}"]
    path_matcher = "neodash-prod"
  }

  # Staging UI
  host_rule {
    hosts        = ["kb.staging.${var.staging_domain}"]
    path_matcher = "neodash-staging"
  }

  # Matchers
  path_matcher {
    name            = "neodash-prod"
    default_service = google_compute_backend_service.neodash_backend.id
  }

  path_matcher {
    name            = "neodash-staging"
    default_service = google_compute_backend_service.neodash_staging_backend.id
  }
}

# -----------------------------------------------------------------------------
# Frontend (Forwarding Rule)
# -----------------------------------------------------------------------------

resource "google_compute_target_https_proxy" "default" {
  name             = "kb-https-proxy"
  url_map          = google_compute_url_map.default.id
  project          = var.project_id
  ssl_certificates = [google_compute_managed_ssl_certificate.cert_v3.id]
}

resource "google_compute_global_forwarding_rule" "default" {
  name       = "kb-forwarding-rule"
  target     = google_compute_target_https_proxy.default.id
  port_range = "443"
  project    = var.project_id
  ip_address = google_compute_global_address.lb_ip.address
}

# -----------------------------------------------------------------------------
# HTTP to HTTPS Redirect
# -----------------------------------------------------------------------------

resource "google_compute_url_map" "https_redirect" {
  name    = "kb-https-redirect"
  project = var.project_id

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "http_redirect" {
  name    = "kb-http-redirect-proxy"
  url_map = google_compute_url_map.https_redirect.id
  project = var.project_id
}

resource "google_compute_global_forwarding_rule" "http_redirect" {
  name       = "kb-http-redirect-rule"
  target     = google_compute_target_http_proxy.http_redirect.id
  port_range = "80"
  project    = var.project_id
  ip_address = google_compute_global_address.lb_ip.address
}
