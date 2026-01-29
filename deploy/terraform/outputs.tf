output "slack_bot_url" {
  description = "URL of the Slack bot Cloud Run service"
  value       = google_cloud_run_v2_service.slack_bot.uri
}

output "neo4j_url" {
  description = "URL of the Neo4j Cloud Run service"
  value       = google_cloud_run_v2_service.neo4j.uri
}

output "duckdb_internal_ip" {
  description = "Internal IP of the DuckDB server"
  value       = google_compute_instance.duckdb.network_interface[0].network_ip
}

output "vpc_connector_id" {
  description = "VPC connector ID for Cloud Run"
  value       = google_vpc_access_connector.connector.id
}
