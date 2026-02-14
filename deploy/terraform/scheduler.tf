# Cloud Scheduler Service Account
resource "google_service_account" "scheduler" {
  account_id   = "scheduler"
  display_name = "Cloud Scheduler Service Account"
}

# Grant scheduler permission to invoke Cloud Run jobs
resource "google_project_iam_member" "scheduler_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

# NOTE: Pipeline scheduler jobs (confluence-sync, parse, metadata, index-rebuild,
# quality-scoring, sync-pipeline) have been removed. Intake jobs are run manually
# until a proper sync strategy is defined. Only backup-related schedulers remain
# (staging-data-refresh-nightly, dr-recovery-test-monthly) — see backup.tf.
