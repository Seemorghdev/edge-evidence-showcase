#!/usr/bin/env bash
set -euo pipefail

mode="${1:---local}"
case "${mode}" in
  --offline|--local) ;;
  *)
    echo "usage: preflight.sh [--offline|--local]" >&2
    exit 2
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
contract="${root}/deploy/deployment-contract.json"

python3 - "${contract}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
assert data["schema"] == "edge-evidence-showcase-deployment.v1"
assert data["stage"] == "service-owned-terraform-planning"
assert data["deployment_authorized"] is False
assert data["credential_source"] == "local-executor-only"
assert data["image"]["same_image_required_for_all_providers"] is True
assert data["providers"]["heroku"]["preexisting_app_required"] is True
assert data["terraform"] == {
    "path": "infra/cloud-run",
    "terraform_version": "1.16.0",
    "provider_source": "hashicorp/google",
    "provider_version": "7.46.0",
    "backend_configured": False,
    "mock_provider_tests": True,
    "real_provider_plan_authorized": False,
    "real_provider_apply_authorized": False,
    "allowed_resource_types": [
        "google_cloud_run_v2_service",
        "google_cloud_run_v2_service_iam_member",
    ],
}
assert data["execution_guards"] == {
    "SHOWCASE_DEPLOYMENT_APPROVED": "1",
    "SHOWCASE_DEPLOYMENT_EXECUTOR": "local",
}
assert data["required_evidence"]
assert data["prohibited"]
PY

for tool in bash python3 docker curl terraform; do
  command -v "${tool}" >/dev/null || {
    echo "required local tool is missing: ${tool}" >&2
    exit 1
  }
done

terraform_version="$(terraform version -json | python3 -c 'import json,sys; print(json.load(sys.stdin)["terraform_version"])')"
if [[ "${terraform_version}" != "1.16.0" ]]; then
  echo "Terraform 1.16.0 is required; found ${terraform_version}" >&2
  exit 1
fi

bash -n "${root}/deploy/cloud-run.sh"
bash -n "${root}/deploy/heroku.sh"
bash -n "${root}/deploy/preflight.sh"

if [[ "${mode}" == "--offline" ]]; then
  echo "credential-free deployment and Terraform preparation validated"
  exit 0
fi

command -v gcloud >/dev/null || {
  echo "required local tool is missing: gcloud" >&2
  exit 1
}

for name in GCP_PROJECT_ID GCP_REGION GCP_CLOUD_RUN_SERVICE HEROKU_APP_NAME; do
  if [[ -z "${!name:-}" ]]; then
    echo "required configuration name is unset: ${name}" >&2
    exit 1
  fi
done

if [[ -n "${HEROKU_API_KEY:-}" ]]; then
  echo "local deployment tools and configuration names are ready; credential value was not printed"
else
  echo "HEROKU_API_KEY is not present in this shell; no credential was requested or inspected"
fi
