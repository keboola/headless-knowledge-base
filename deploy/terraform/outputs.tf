output "slack_bot_url" {
  description = "URL of the Slack bot Cloud Run service"
  value       = google_cloud_run_v2_service.slack_bot.uri
}

output "chromadb_url" {
  description = "URL of the ChromaDB Cloud Run service"
  value       = google_cloud_run_v2_service.chromadb.uri
}

output "duckdb_internal_ip" {
  description = "Internal IP of the DuckDB server"
  value       = google_compute_instance.duckdb.network_interface[0].network_ip
}

output "vpc_connector_id" {
  description = "VPC connector ID for Cloud Run"
  value       = google_vpc_access_connector.connector.id
}
