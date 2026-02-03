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

variable "base_domain" {
  description = "Base domain for production (e.g. keboola.com)"
  type        = string
  default     = "keboola.com"
}

variable "staging_domain" {
  description = "Base domain for staging (e.g. keboola.dev)"
  type        = string
  default     = "keboola.dev"
}

variable "iap_support_email" {
  description = "Email address for IAP brand support"
  type        = string
}

variable "iap_authorized_users" {
  description = "List of users/groups/domains authorized to access the Web UI via IAP (e.g. ['user:me@example.com', 'domain:example.com'])"
  type        = list(string)
  default     = []
}

# -----------------------------------------------------------------------------
# Staging Environment Variables
# -----------------------------------------------------------------------------
variable "neo4j_auth_staging" {
  description = "Neo4j authentication string for staging (format: neo4j/password)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "neo4j_password_staging" {
  description = "Neo4j password for staging (for client connections)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "slack_bot_token_staging" {
  description = "Slack bot token for staging app"
  type        = string
  sensitive   = true
  default     = "placeholder-token"
}

variable "slack_signing_secret_staging" {
  description = "Slack signing secret for staging app"
  type        = string
  sensitive   = true
  default     = "placeholder-secret"
}
