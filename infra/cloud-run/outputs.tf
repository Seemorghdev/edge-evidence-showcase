output "image_uri" {
  description = "Immutable image URI configured on the service."
  value       = local.image_uri
}

output "service_name" {
  description = "Cloud Run service name."
  value       = google_cloud_run_v2_service.showcase.name
}

output "service_uri" {
  description = "Provider-returned Cloud Run service URI after apply."
  value       = google_cloud_run_v2_service.showcase.uri
}

output "latest_ready_revision" {
  description = "Provider-returned latest ready revision after apply."
  value       = google_cloud_run_v2_service.showcase.latest_ready_revision
}

output "public_invocation_enabled" {
  description = "Whether this configuration grants allUsers roles/run.invoker."
  value       = var.allow_public_invocation
}
