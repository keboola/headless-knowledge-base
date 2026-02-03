output "load_balancer_ip" {
  description = "The static IP address of the Global External HTTP(S) Load Balancer (for UI)"
  value       = google_compute_global_address.lb_ip.address
}

output "db_prod_ip" {
  description = "The static IP address of the SSL Proxy Load Balancer for Production DB"
  value       = google_compute_global_address.db_ip.address
}

output "db_staging_ip" {
  description = "The static IP address of the SSL Proxy Load Balancer for Staging DB"
  value       = google_compute_global_address.db_staging_ip.address
}

output "slack_bot_url" {
  description = "URL of the Slack bot Cloud Run service"
  value       = google_cloud_run_v2_service.slack_bot.uri
}

output "staging_slack_bot_url" {
  value       = google_cloud_run_v2_service.slack_bot_staging.uri
  description = "URL of the staging Slack bot Cloud Run service"
}