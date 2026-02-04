# =============================================================================
# Production Neo4j VM (Compute Engine)
# =============================================================================
# Replacing Cloud Run to support SSL Proxy Load Balancing (TCP/Bolt)
# =============================================================================

resource "google_compute_instance" "neo4j_prod" {
  name         = "neo4j-prod"
  machine_type = "e2-standard-2" # 2 vCPU, 8GB RAM
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 20
      type  = "pd-ssd"
    }
  }

  # Data disk for Neo4j
  attached_disk {
    source      = google_compute_disk.neo4j_prod_data.self_link
    device_name = "neo4j-prod-data"
    mode        = "READ_WRITE"
  }

  network_interface {
    subnetwork = google_compute_subnetwork.main.self_link
    # No external IP - access via VPC only
  }

  metadata = {
    neo4j-password = random_password.neo4j_prod_password.result
    startup-script = file("${path.module}/scripts/neo4j-prod-startup.sh")
  }

  service_account {
    email  = google_service_account.neo4j.email
    scopes = ["cloud-platform"]
  }

  tags = ["neo4j-prod"]

  allow_stopping_for_update = true
}

resource "google_compute_disk" "neo4j_prod_data" {
  name = "neo4j-prod-data-disk"
  type = "pd-ssd"
  zone = var.zone
  size = 50 # 50GB for Production

  labels = {
    environment = "prod"
    purpose     = "neo4j-data"
  }
}

# Firewall rule to allow Bolt connections from VPC (Internal services)
resource "google_compute_firewall" "neo4j_prod_internal" {
  name    = "allow-neo4j-prod-internal"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["7687", "7474"]
  }

  source_ranges = ["10.0.0.0/24", "10.8.0.0/28"] # VPC subnet + VPC connector
  target_tags   = ["neo4j-prod"]
}

# Firewall rule to allow Google Load Balancer (Health Checks + Traffic)
resource "google_compute_firewall" "neo4j_prod_lb" {
  name    = "allow-neo4j-prod-lb"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["7687", "7474"]
  }

  source_ranges = ["130.211.0.0/22", "35.191.0.0/16"] 
  target_tags   = ["neo4j-prod"]
}

# NEG for Production Neo4j (to expose via SSL Proxy LB)
resource "google_compute_network_endpoint_group" "neo4j_prod_neg" {
  name                  = "neo4j-prod-neg"
  network               = google_compute_network.main.id
  subnetwork            = google_compute_subnetwork.main.id
  default_port          = 7474
  zone                  = var.zone
  network_endpoint_type = "GCE_VM_IP_PORT"
  project               = var.project_id
}

resource "google_compute_network_endpoint" "neo4j_prod_endpoint" {
  network_endpoint_group = google_compute_network_endpoint_group.neo4j_prod_neg.name
  instance               = google_compute_instance.neo4j_prod.name
  port                   = google_compute_network_endpoint_group.neo4j_prod_neg.default_port
  ip_address             = google_compute_instance.neo4j_prod.network_interface[0].network_ip
  zone                   = var.zone
  project                = var.project_id
}

# Generate random password for production Neo4j
resource "random_password" "neo4j_prod_password" {
  length           = 16
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}
