# Cloud Run local-executor execution packet

Status: **STOP BEFORE REAL PROVIDER PLAN OR APPLY**

This packet prepares the separately approved local credentialed executor. Repository
and public CI validation stop after formatting, schema validation, mocked plan tests,
and policy fixtures. No credential discovery, Google API plan, state creation, apply,
IAM mutation, service creation, URL verification, or rollback is performed here.

## Required owner-approved non-secret coordinates

Freeze these exact values before provider access:

| Coordinate | Terraform input | Requirement |
| --- | --- | --- |
| Google Cloud project | `project_id` | Existing project with billing and required APIs already managed elsewhere |
| Region | `region` | Existing Cloud Run and Artifact Registry region |
| Artifact Registry repository | `artifact_registry_repository` | Existing Docker repository |
| Image name | `image_name` | Existing image path inside that repository |
| Immutable image digest | `image_digest` | Exact `sha256:<64 lowercase hex>` digest |
| Cloud Run service | `service_name` | Exact existing or explicitly approved new service name |
| Runtime identity | `service_account_email` | Existing least-privilege service account |
| Public invocation decision | `allow_public_invocation` | `false` unless owner explicitly approves `allUsers` |

Also freeze the source commit/tree, cost ceiling, whether service creation is allowed,
whether an existing service must be imported, the previous image digest and revision,
the state-retention location, and the evidence-retention location.

## Authentication prerequisite

Use Google Application Default Credentials only on the approved local executor. Do not
paste credentials or tokens into chat, Terraform variables, tfvars, Git, logs, or
evidence.

Before planning, the executor must already have an approved identity able to:

- read and create/update the named Cloud Run service as authorized;
- act as the named runtime service account;
- read the immutable Artifact Registry image;
- get/set only the named service's IAM policy when public invocation is approved.

A typical interactive prerequisite is:

```bash
gcloud auth application-default login
gcloud auth application-default print-access-token >/dev/null
```

Impersonation or workforce/workload federation may replace interactive login when
already approved. Repository authority does not choose or grant the identity.

## Prepare a private execution directory

Do not create Terraform state in the public checkout.

```bash
set -euo pipefail
umask 077
REPO_ROOT="$(git rev-parse --show-toplevel)"
: "${SHOWCASE_EXECUTION_ROOT:?set an approved private execution directory}"
test ! -e "${SHOWCASE_EXECUTION_ROOT}/.git"
mkdir -p "${SHOWCASE_EXECUTION_ROOT}"
cp -R "${REPO_ROOT}/infra/cloud-run/." "${SHOWCASE_EXECUTION_ROOT}/"
cd "${SHOWCASE_EXECUTION_ROOT}"
cp terraform.tfvars.example terraform.tfvars
```

Edit only `terraform.tfvars` in the private execution directory. Never commit it.

## Offline/static gate

```bash
terraform version
test "$(terraform version -json | python3 -c 'import json,sys; print(json.load(sys.stdin)["terraform_version"])')" = "1.16.0"
terraform init -backend=false -input=false
terraform fmt -check -recursive
terraform validate
terraform test -no-color
python3 policy/check_source.py
python3 policy/check_plan.py policy/fixtures/private-plan.json --expect-public false
python3 policy/check_plan.py policy/fixtures/public-plan.json --expect-public true
if python3 policy/check_plan.py policy/fixtures/destructive-plan.json --expect-public false; then
  exit 1
fi
```

The executor must inspect `terraform.tfvars` and confirm every value matches the frozen
packet before continuing.

## Existing-resource readback and import decision

Read the named service without printing credentials:

```bash
gcloud run services describe "${TF_VAR_service_name}" \
  --project="${TF_VAR_project_id}" \
  --region="${TF_VAR_region}" \
  --format='yaml(metadata.name,status.latestReadyRevisionName,status.traffic,status.url,spec.template.spec.serviceAccountName)'
```

If the service exists, import it before planning:

```bash
terraform import \
  google_cloud_run_v2_service.showcase \
  "projects/${TF_VAR_project_id}/locations/${TF_VAR_region}/services/${TF_VAR_service_name}"
```

When public invocation is approved and the exact `allUsers` member already exists,
import it using the provider-documented IAM member identifier. Stop rather than
creating a duplicate or replacing an authoritative policy.

If the service is absent and creation is not explicitly approved, stop.

## Exact provider plan commands

These commands are prepared for the local executor but are not run by repository CI:

```bash
set -euo pipefail
umask 077
gcloud auth application-default print-access-token >/dev/null
terraform init -input=false -upgrade=false
terraform validate
terraform plan \
  -input=false \
  -lock-timeout=60s \
  -out=showcase.tfplan
terraform show -json showcase.tfplan > showcase.tfplan.json
python3 policy/check_plan.py \
  showcase.tfplan.json \
  --expect-public "${TF_VAR_allow_public_invocation}"
terraform show -no-color showcase.tfplan > showcase.tfplan.txt
sha256sum showcase.tfplan showcase.tfplan.json showcase.tfplan.txt
```

## Expected diff

For an explicitly approved new service:

- create exactly `google_cloud_run_v2_service.showcase`;
- create exactly one
  `google_cloud_run_v2_service_iam_member.public_invoker[0]` only when
  `allow_public_invocation=true`;
- create no project, API enablement, repository, image, service account, key, backend,
  broad IAM binding, monitoring resource, network, database, Kubernetes resource, or
  secret;
- configure the immutable image digest, runtime service account, port `8080`, CPU `1`,
  memory `512Mi`, concurrency `1`, min instances `0`, max instances `3`, timeout
  `120s`, `/readyz` startup probe, `/healthz` liveness probe, and deletion protection.

For an imported service, only an in-place update or no-op is acceptable. Stop on any
destroy, replacement, unapproved IAM action, different coordinate, mutable image tag,
resource outside the two allowed addresses, or cost boundary mismatch.

## Exact apply commands

Apply only the reviewed binary plan whose hashes were retained:

```bash
terraform apply -input=false showcase.tfplan
terraform output -json > terraform-output.json
sha256sum terraform-output.json
```

Never rerun `terraform plan` implicitly through `terraform apply` without the reviewed
plan file.

## Smoke and evidence capture

```bash
SERVICE_URL="$(terraform output -raw service_uri)"
python3 "${REPO_ROOT}/scripts/smoke_live.py" \
  --url "${SERVICE_URL}" \
  | tee cloud-run-smoke.json
sha256sum cloud-run-smoke.json

gcloud run services describe "${TF_VAR_service_name}" \
  --project="${TF_VAR_project_id}" \
  --region="${TF_VAR_region}" \
  --format='yaml(metadata.name,status.latestCreatedRevisionName,status.latestReadyRevisionName,status.traffic,status.url)' \
  > cloud-run-readback.yaml
sha256sum cloud-run-readback.yaml
```

Retain privately:

- source commit and tree;
- Terraform and provider versions;
- sanitized non-secret coordinates and owner decisions;
- immutable image digest;
- plan binary, JSON, text, and SHA-256 values;
- state-before and state-after backups in the approved state location;
- previous and new revision/image identities;
- apply result;
- service readback and URL;
- smoke receipt and SHA-256;
- observed cost boundary;
- rollback plan, apply, readback, and smoke receipt.

Do not retain access tokens, ADC files, authorization headers, account inventories, or
full environment dumps.

## Rollback

Preferred rollback preserves Terraform ownership by returning to the exact previous
image digest and public-invocation decision:

```bash
export TF_VAR_image_digest="${PREVIOUS_IMAGE_DIGEST:?}"
export TF_VAR_allow_public_invocation="${PREVIOUS_PUBLIC_INVOCATION:?true or false}"
terraform plan \
  -input=false \
  -lock-timeout=60s \
  -out=rollback.tfplan
terraform show -json rollback.tfplan > rollback.tfplan.json
python3 policy/check_plan.py \
  rollback.tfplan.json \
  --expect-public "${TF_VAR_allow_public_invocation}"
terraform apply -input=false rollback.tfplan
python3 "${REPO_ROOT}/scripts/smoke_live.py" \
  --url "$(terraform output -raw service_uri)" \
  | tee rollback-smoke.json
```

Read back the latest ready revision and traffic after rollback. A first-creation
teardown requires a separate destructive owner approval; do not use `terraform
destroy` as an automatic rollback.

## Stop conditions

Stop before plan or apply when credentials are unavailable, any coordinate is
unfrozen, the image is not an immutable digest, state retention is unresolved, service
creation or public invocation lacks approval, an existing service is not imported, the
plan contains deletion/replacement or any resource outside the allowlist, expected cost
caps differ, rollback inputs are absent, or any command would expose a credential.
