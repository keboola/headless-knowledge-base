variable "project_id" {
  description = "GCP Project ID"
  type        = string
  default     = "ai-knowledge-base-42"
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP Zone"
  type        = string
  default     = "us-central1-a"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "confluence_base_url" {
  description = "Confluence base URL"
  type        = string
  default     = ""
}

variable "confluence_space_keys" {
  description = "Comma-separated list of Confluence space keys to sync"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# Staging Environment Variables
# -----------------------------------------------------------------------------
variable "chromadb_token_staging" {
  description = "ChromaDB authentication token for staging"
  type        = string
  sensitive   = true
  default     = ""
}

variable "slack_bot_token_staging" {
  description = "Slack bot token for staging app"
  type        = string
  sensitive   = true
  default     = ""
}

variable "slack_signing_secret_staging" {
  description = "Slack signing secret for staging app"
  type        = string
  sensitive   = true
  default     = ""
}
