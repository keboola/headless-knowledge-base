# =============================================================================
# Web Assets Storage
# =============================================================================

resource "google_storage_bucket" "web_assets" {
  name     = "${var.project_id}-web-assets"
  location = var.region
  project  = var.project_id

  uniform_bucket_level_access = true
  
  # Allow public read for dashboard config (or we can restrict to IAP if needed, 
  # but Neodash is client-side, so it needs to fetch it)
  # For now, we'll keep it private and use signed URLs or just allow all users 
  # if it's not sensitive. Since it's behind IAP anyway (the UI is), 
  # but the browser needs to fetch the JSON.
}

# Upload the dashboard config
resource "google_storage_bucket_object" "dashboard_config" {
  name   = "dashboards/default.json"
  source = "../../src/knowledge_base/web/dashboard_config.json"
  bucket = google_storage_bucket.web_assets.name
}

# Allow public read access to the dashboard config (required for Neodash browser client)
resource "google_storage_bucket_iam_member" "public_read_dashboard" {
  bucket = google_storage_bucket.web_assets.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

output "dashboard_config_url" {
  value = "https://storage.googleapis.com/${google_storage_bucket.web_assets.name}/${google_storage_bucket_object.dashboard_config.name}"
}
