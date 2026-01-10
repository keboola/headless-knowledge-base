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

# ChromaDB Auth Token
resource "google_secret_manager_secret" "chromadb_token" {
  secret_id = "chromadb-token"

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    purpose     = "chromadb"
  }
}

resource "google_secret_manager_secret_version" "chromadb_token" {
  secret      = google_secret_manager_secret.chromadb_token.id
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

resource "google_secret_manager_secret_iam_member" "slack_chromadb_access" {
  secret_id = google_secret_manager_secret.chromadb_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.slack_bot.email}"
}

# ChromaDB service account secret access
resource "google_secret_manager_secret_iam_member" "chromadb_token_access" {
  secret_id = google_secret_manager_secret.chromadb_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.chromadb.email}"
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

resource "google_secret_manager_secret_iam_member" "jobs_chromadb_access" {
  secret_id = google_secret_manager_secret.chromadb_token.secret_id
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
