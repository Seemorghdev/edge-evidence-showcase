#!/usr/bin/env bash
set -euo pipefail

image_uri="${1:?usage: cloud-run.sh IMAGE_URI_WITH_DIGEST}"

if [[ "${SHOWCASE_DEPLOYMENT_APPROVED:-}" != "1" ]]; then
  echo "SHOWCASE_DEPLOYMENT_APPROVED=1 is required" >&2
  exit 2
fi
if [[ "${SHOWCASE_DEPLOYMENT_EXECUTOR:-}" != "local" ]]; then
  echo "SHOWCASE_DEPLOYMENT_EXECUTOR=local is required" >&2
  exit 2
fi
if [[ "${image_uri}" != *@sha256:* ]]; then
  echo "Cloud Run deployment requires an immutable image digest" >&2
  exit 2
fi

gcp_project_ref="${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
region="${GCP_REGION:?GCP_REGION is required}"
service="${GCP_CLOUD_RUN_SERVICE:?GCP_CLOUD_RUN_SERVICE is required}"

service_exists=0
if gcloud run services describe "${service}" \
  --project="${gcp_project_ref}" \
  --region="${region}" >/dev/null 2>&1; then
  service_exists=1
fi

if [[ "${service_exists}" != "1" && "${SHOWCASE_ALLOW_CREATE_CLOUD_RUN_SERVICE:-0}" != "1" ]]; then
  echo "Cloud Run service does not exist; explicit creation approval is required" >&2
  exit 2
fi

auth_args=()
if [[ "${SHOWCASE_ALLOW_PUBLIC_INVOCATION:-0}" == "1" ]]; then
  auth_args+=(--allow-unauthenticated)
fi

gcloud run deploy "${service}" \
  --project="${gcp_project_ref}" \
  --region="${region}" \
  --image="${image_uri}" \
  "${auth_args[@]}" \
  --ingress=all \
  --port=8080 \
  --min=0 \
  --max=3 \
  --cpu=1 \
  --memory=512Mi \
  --concurrency=1 \
  --timeout=120s \
  --cpu-throttling \
  --no-cpu-boost \
  --no-session-affinity \
  --deploy-health-check \
  --startup-probe="httpGet.path=/readyz,httpGet.port=8080,initialDelaySeconds=0,failureThreshold=12,timeoutSeconds=2,periodSeconds=5" \
  --readiness-probe="httpGet.path=/readyz,httpGet.port=8080,failureThreshold=3,successThreshold=1,timeoutSeconds=2,periodSeconds=5" \
  --liveness-probe="httpGet.path=/healthz,httpGet.port=8080,initialDelaySeconds=5,failureThreshold=3,timeoutSeconds=2,periodSeconds=15" \
  --set-env-vars="SHOWCASE_PUBLIC_MODE=synthetic-stateless,SHOWCASE_DEMO_TIMEOUT_SECONDS=105" \
  --description="Synthetic stateless edge-evidence showcase; no private evidence or persistent authority" \
  --quiet

gcloud run services describe "${service}" \
  --project="${gcp_project_ref}" \
  --region="${region}" \
  --format='value(status.url)'
