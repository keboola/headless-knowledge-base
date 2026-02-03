# DuckDB Server Instance
resource "google_compute_instance" "duckdb" {
  name         = "duckdb-server"
  machine_type = "e2-micro"
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 10
      type  = "pd-standard"
    }
  }

  # Data disk for DuckDB
  attached_disk {
    source      = google_compute_disk.duckdb_data.self_link
    device_name = "duckdb-data"
    mode        = "READ_WRITE"
  }

  network_interface {
    subnetwork = google_compute_subnetwork.main.self_link
    # No external IP - access via VPC only
  }

  metadata_startup_script = file("${path.module}/scripts/duckdb-startup.sh")

  service_account {
    email  = google_service_account.duckdb.email
    scopes = ["cloud-platform"]
  }

  tags = ["duckdb-server"]

  # Allow stopping for updates
  allow_stopping_for_update = true
}

resource "google_compute_disk" "duckdb_data" {
  name = "duckdb-data-disk"
  type = "pd-ssd"
  zone = var.zone
  size = 20

  labels = {
    environment = var.environment
    purpose     = "duckdb-data"
  }
}

resource "google_service_account" "duckdb" {
  account_id   = "duckdb-server"
  display_name = "DuckDB Server Service Account"
}

# Grant DuckDB service account access to Cloud Storage (for backups)
resource "google_project_iam_member" "duckdb_storage" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.duckdb.email}"
}
