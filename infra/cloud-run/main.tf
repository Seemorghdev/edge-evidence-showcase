locals {
  image_uri = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_registry_repository}/${var.image_name}@${var.image_digest}"
}

resource "google_cloud_run_v2_service" "showcase" {
  project             = var.project_id
  name                = var.service_name
  location            = var.region
  description         = "Synthetic edge-evidence showcase"
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true

  labels = {
    component           = "edge-evidence-showcase"
    data_classification = "synthetic"
    managed_by          = "terraform"
  }

  template {
    service_account                  = var.service_account_email
    timeout                          = "120s"
    max_instance_request_concurrency = 1

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      name  = "showcase"
      image = local.image_uri

      ports {
        container_port = 8080
      }

      resources {
        cpu_idle = true

        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 2
        period_seconds        = 2
        failure_threshold     = 60

        http_get {
          path = "/readyz"
          port = 8080
        }
      }

      liveness_probe {
        initial_delay_seconds = 5
        timeout_seconds       = 2
        period_seconds        = 10
        failure_threshold     = 3

        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count = var.allow_public_invocation ? 1 : 0

  project  = google_cloud_run_v2_service.showcase.project
  location = google_cloud_run_v2_service.showcase.location
  name     = google_cloud_run_v2_service.showcase.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
