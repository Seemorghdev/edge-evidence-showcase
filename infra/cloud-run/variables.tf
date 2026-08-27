variable "project_id" {
  description = "Already-approved Google Cloud project ID. This example never creates a project."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid 6-30 character Google Cloud project ID."
  }
}

variable "region" {
  description = "Already-approved Cloud Run and Artifact Registry region."
  type        = string

  validation {
    condition     = can(regex("^[a-z]+-[a-z0-9]+[0-9]$", var.region))
    error_message = "region must be a regional Google Cloud location such as europe-west1."
  }
}

variable "artifact_registry_repository" {
  description = "Name of an existing Artifact Registry Docker repository in project_id and region."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,62}$", var.artifact_registry_repository))
    error_message = "artifact_registry_repository must be a valid existing repository name."
  }
}

variable "image_name" {
  description = "Docker image name inside the existing Artifact Registry repository."
  type        = string
  default     = "showcase"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._/-]{0,126}$", var.image_name))
    error_message = "image_name must be a lowercase Artifact Registry image path."
  }
}

variable "image_digest" {
  description = "Immutable sha256 digest of the already-pushed canonical runtime image."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be an immutable sha256 digest."
  }
}

variable "service_name" {
  description = "Already-approved Cloud Run service name."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,61}[a-z0-9]$", var.service_name))
    error_message = "service_name must be a valid lowercase Cloud Run service name."
  }
}

variable "service_account_email" {
  description = "Email of an existing least-privilege runtime service account."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\\.iam\\.gserviceaccount\\.com$", var.service_account_email))
    error_message = "service_account_email must identify an existing Google service account."
  }
}

variable "allow_public_invocation" {
  description = "Owner-approved decision to grant roles/run.invoker to allUsers."
  type        = bool
  default     = false
}
