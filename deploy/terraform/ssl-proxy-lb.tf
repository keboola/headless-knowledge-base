# =============================================================================
# SSL Proxy Load Balancer (for Neo4j Database Access)
# =============================================================================
# This LB handles the Database traffic via direct SSL/TCP.
# It effectively replaces the "HTTP" route for neo4j.* domains.
# =============================================================================

# Global Static IP for DB
resource "google_compute_global_address" "db_ip" {
  name    = "kb-db-load-balancer-ip"
  project = var.project_id
}

# SSL Certificate for DB (Valid for neo4j.internal and neo4j.staging)
resource "google_compute_managed_ssl_certificate" "db_cert" {
  name    = "kb-db-cert"
  project = var.project_id

  managed {
    domains = [
      "neo4j.internal.${var.base_domain}",
      "neo4j.staging.${var.staging_domain}"
    ]
  }
}

# -----------------------------------------------------------------------------
# Backend Services (SSL)
# -----------------------------------------------------------------------------

resource "google_compute_backend_service" "neo4j_prod_ssl" {

  name          = "neo4j-prod-ssl"

  protocol      = "TCP"

  timeout_sec   = 3600

  project       = var.project_id

  

  backend {

    group                        = google_compute_network_endpoint_group.neo4j_prod_neg.id

    balancing_mode               = "CONNECTION"

    max_connections_per_endpoint = 100

  }



  health_checks = [google_compute_health_check.neo4j_http_health.id]

}



resource "google_compute_backend_service" "neo4j_staging_ssl" {

  name          = "neo4j-staging-ssl"

  protocol      = "TCP"

  timeout_sec   = 3600

  project       = var.project_id



  backend {

    group                        = google_compute_network_endpoint_group.neo4j_staging_neg.id

    balancing_mode               = "CONNECTION"

    max_connections_per_endpoint = 100

  }



  health_checks = [google_compute_health_check.neo4j_http_health.id]

}



# TCP Health Check (Checks if Bolt port is responding)

resource "google_compute_health_check" "neo4j_http_health" {

  name    = "neo4j-ssl-proxy-health"

  project = var.project_id



  tcp_health_check {

    port = 7687

  }

}

# -----------------------------------------------------------------------------
# SSL Proxy Frontend
# -----------------------------------------------------------------------------

resource "google_compute_target_ssl_proxy" "db_proxy" {
  name             = "kb-db-ssl-proxy"
  project          = var.project_id
  backend_service  = google_compute_backend_service.neo4j_prod_ssl.id # Default to Prod
  ssl_certificates = [google_compute_managed_ssl_certificate.db_cert.id]
}

# Forwarding Rule
resource "google_compute_global_forwarding_rule" "db_forwarding_rule" {
  name       = "kb-db-forwarding-rule"
  target     = google_compute_target_ssl_proxy.db_proxy.id
  port_range = "443"
  project    = var.project_id
  ip_address = google_compute_global_address.db_ip.address
  load_balancing_scheme = "EXTERNAL"
}

# -----------------------------------------------------------------------------
# IMPORTANT: SSL Proxy does NOT support Host-based routing (URL Maps)
# -----------------------------------------------------------------------------
# We have ONE IP. We can only point to ONE backend service based on that IP.
# If we want Prod and Staging on port 443, we need TWO IPs.
# Or we use SNI? 
# "Target SSL Proxies support SNI."
# BUT, they don't support routing traffic to *different backend services* based on SNI.
# They only use SNI to select the certificate.
# The traffic always goes to the defined `backend_service`.

# CONCLUSION: We need TWO IPs. One for Prod DB, One for Staging DB.
# Or we run Staging on a different port (e.g. 8443).
# Let's create a second IP for Staging DB to keep it clean (Standard 443).

# -----------------------------------------------------------------------------
# Staging DB SSL Proxy (Separate IP)
# -----------------------------------------------------------------------------

resource "google_compute_global_address" "db_staging_ip" {
  name    = "kb-db-staging-ip"
  project = var.project_id
}

resource "google_compute_target_ssl_proxy" "db_staging_proxy" {
  name             = "kb-db-staging-proxy"
  project          = var.project_id
  backend_service  = google_compute_backend_service.neo4j_staging_ssl.id
  ssl_certificates = [google_compute_managed_ssl_certificate.db_cert.id] # Same cert is fine (multi-domain)
}

resource "google_compute_global_forwarding_rule" "db_staging_forwarding_rule" {
  name       = "kb-db-staging-forwarding-rule"
  target     = google_compute_target_ssl_proxy.db_staging_proxy.id
  port_range = "443"
  project    = var.project_id
  ip_address = google_compute_global_address.db_staging_ip.address
  load_balancing_scheme = "EXTERNAL"
}
