#!/usr/bin/env bash
set -euo pipefail

image_uri="${1:?usage: cloud-run.sh IMAGE_URI}"
gcp_project_ref="${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
region="${GCP_REGION:-europe-west1}"
service="${GCP_CLOUD_RUN_SERVICE:-edge-evidence-showcase}"

gcloud run deploy "${service}" \
  --project="${gcp_project_ref}" \
  --region="${region}" \
  --image="${image_uri}" \
  --allow-unauthenticated \
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
