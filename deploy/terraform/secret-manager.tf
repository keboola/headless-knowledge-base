# =============================================================================
# Secret Manager Configuration
# =============================================================================

# Slack Bot Token
resource "google_secret_manager_secret" "slack_bot_token" {
  secret_id = "slack-bot-token"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "slack"
  }
}

resource "google_secret_manager_secret_version" "slack_bot_token" {
  secret      = google_secret_manager_secret.slack_bot_token.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Slack Signing Secret
resource "google_secret_manager_secret" "slack_signing_secret" {
  secret_id = "slack-signing-secret"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "slack"
  }
}

resource "google_secret_manager_secret_version" "slack_signing_secret" {
  secret      = google_secret_manager_secret.slack_signing_secret.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Anthropic API Key
resource "google_secret_manager_secret" "anthropic_api_key" {
  secret_id = "anthropic-api-key"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "llm"
  }
}

resource "google_secret_manager_secret_version" "anthropic_api_key" {
  secret      = google_secret_manager_secret.anthropic_api_key.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Confluence Email
resource "google_secret_manager_secret" "confluence_email" {
  secret_id = "confluence-email"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "confluence"
  }
}

resource "google_secret_manager_secret_version" "confluence_email" {
  secret      = google_secret_manager_secret.confluence_email.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Confluence API Token
resource "google_secret_manager_secret" "confluence_api_token" {
  secret_id = "confluence-api-token"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "confluence"
  }
}

resource "google_secret_manager_secret_version" "confluence_api_token" {
  secret      = google_secret_manager_secret.confluence_api_token.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Neo4j Authentication (format: "neo4j/password")
resource "google_secret_manager_secret" "neo4j_auth" {
  secret_id = "neo4j-auth"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "neo4j"
  }
}

resource "google_secret_manager_secret_version" "neo4j_auth" {
  secret      = google_secret_manager_secret.neo4j_auth.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Neo4j Password (for client connections)
resource "google_secret_manager_secret" "neo4j_password" {
  secret_id = "neo4j-password"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "neo4j"
  }
}

resource "google_secret_manager_secret_version" "neo4j_password" {
  secret      = google_secret_manager_secret.neo4j_password.id
  secret_data = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# =============================================================================
# IAM Bindings for Secret Access
# =============================================================================

# Slack Bot service account secret access
resource "google_secret_manager_secret_iam_member" "slack_bot_token_access" {
  secret_id = google_secret_manager_secret.slack_bot_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.slack_bot.email}"
}

resource "google_secret_manager_secret_iam_member" "slack_signing_secret_access" {
  secret_id = google_secret_manager_secret.slack_signing_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.slack_bot.email}"
}

resource "google_secret_manager_secret_iam_member" "slack_anthropic_access" {
  secret_id = google_secret_manager_secret.anthropic_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.slack_bot.email}"
}

# Slack Bot Neo4j password access
resource "google_secret_manager_secret_iam_member" "slack_neo4j_password_access" {
  secret_id = google_secret_manager_secret.neo4j_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.slack_bot.email}"
}

# Neo4j service account secret access
resource "google_secret_manager_secret_iam_member" "neo4j_auth_access" {
  secret_id = google_secret_manager_secret.neo4j_auth.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.neo4j.email}"
}

# Jobs service account secret access
resource "google_secret_manager_secret_iam_member" "jobs_confluence_email_access" {
  secret_id = google_secret_manager_secret.confluence_email.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.jobs.email}"
}

resource "google_secret_manager_secret_iam_member" "jobs_confluence_token_access" {
  secret_id = google_secret_manager_secret.confluence_api_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.jobs.email}"
}

resource "google_secret_manager_secret_iam_member" "jobs_anthropic_access" {
  secret_id = google_secret_manager_secret.anthropic_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.jobs.email}"
}

# Jobs service account Neo4j password access
resource "google_secret_manager_secret_iam_member" "jobs_neo4j_password_access" {
  secret_id = google_secret_manager_secret.neo4j_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.jobs.email}"
}

# =============================================================================
# Vertex AI IAM Bindings
# =============================================================================

# Slack Bot service account Vertex AI access
resource "google_project_iam_member" "slack_bot_vertex_ai" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.slack_bot.email}"
}

# Jobs service account Vertex AI access
resource "google_project_iam_member" "jobs_vertex_ai" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.jobs.email}"
}
