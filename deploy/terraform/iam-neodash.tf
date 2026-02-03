# Allow Neodash service account to access Neo4j password secret
resource "google_secret_manager_secret_iam_member" "neodash_neo4j_password_access" {
  secret_id = google_secret_manager_secret.neo4j_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.neodash.email}"
}
