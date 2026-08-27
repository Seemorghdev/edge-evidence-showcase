mock_provider "google" {
  override_during = plan
}

variables {
  project_id                   = "example-project"
  region                       = "europe-west1"
  artifact_registry_repository = "example-showcase-images"
  image_name                   = "showcase"
  image_digest                 = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  service_name                 = "edge-evidence-showcase"
  service_account_email        = "showcase-runtime\u0040example-project.iam.gserviceaccount.com"
  allow_public_invocation      = false
}

run "private_service_plan" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.showcase.project == var.project_id
    error_message = "The service must target only the supplied project."
  }

  assert {
    condition     = google_cloud_run_v2_service.showcase.location == var.region
    error_message = "The service and image region must remain explicit."
  }

  assert {
    condition     = google_cloud_run_v2_service.showcase.deletion_protection
    error_message = "Deletion protection must be enabled."
  }

  assert {
    condition     = google_cloud_run_v2_service.showcase.template[0].service_account == var.service_account_email
    error_message = "The revision must use the supplied existing runtime identity."
  }

  assert {
    condition     = google_cloud_run_v2_service.showcase.template[0].max_instance_request_concurrency == 1
    error_message = "Request concurrency must remain one."
  }

  assert {
    condition     = google_cloud_run_v2_service.showcase.template[0].scaling[0].min_instance_count == 0 && google_cloud_run_v2_service.showcase.template[0].scaling[0].max_instance_count == 3
    error_message = "Scaling must remain bounded between zero and three instances."
  }

  assert {
    condition     = google_cloud_run_v2_service.showcase.template[0].containers[0].resources[0].cpu_idle
    error_message = "Request-based billing must remain explicit when resource limits are set."
  }

  assert {
    condition     = google_cloud_run_v2_service.showcase.template[0].containers[0].image == local.image_uri
    error_message = "The service must use the immutable regional Artifact Registry image."
  }

  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.public_invoker) == 0
    error_message = "Public invocation must be absent by default."
  }
}

run "public_service_plan" {
  command = plan

  variables {
    allow_public_invocation = true
  }

  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.public_invoker) == 1
    error_message = "The public invocation decision must create exactly one narrow IAM member."
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.public_invoker[0].role == "roles/run.invoker"
    error_message = "The public IAM grant must use only roles/run.invoker."
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.public_invoker[0].member == "allUsers"
    error_message = "The optional public IAM grant must target allUsers explicitly."
  }
}
