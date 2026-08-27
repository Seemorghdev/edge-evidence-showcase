# Service-owned Cloud Run Terraform

This directory is a credential-free, state-free example for the synthetic showcase.
It manages only one Cloud Run v2 service and, when separately approved, one
non-authoritative `roles/run.invoker` member for `allUsers`.

It does **not** create or own a Google Cloud project, billing link, API enablement,
Artifact Registry repository, image, runtime service account, organization/folder
policy, state backend, deployment identity, domain, monitoring resource, or credential.

## Pinned toolchain

- Terraform `1.16.0`
- `hashicorp/google` `7.46.0`
- `google_cloud_run_v2_service`
- `google_cloud_run_v2_service_iam_member`

The provider remains on the final reviewed 7.x line rather than adopting the newly
released 8.x major line without a separate compatibility stage.

## Static validation

These commands download the pinned provider schema but make no Google API call and
require no credentials:

```bash
terraform init -backend=false -input=false
terraform fmt -check -recursive
terraform validate
terraform test -no-color
python3 policy/check_source.py
python3 policy/check_plan.py policy/fixtures/private-plan.json --expect-public false
python3 policy/check_plan.py policy/fixtures/public-plan.json --expect-public true
if python3 policy/check_plan.py policy/fixtures/destructive-plan.json --expect-public false; then
  echo "destructive fixture unexpectedly passed" >&2
  exit 1
fi
```

`terraform test` uses `mock_provider "google"` with plan-only runs. It neither
discovers credentials nor contacts a provider API.

## Inputs and ownership

Copy `terraform.tfvars.example` only into a private execution directory outside the
repository. Replace placeholders with owner-approved, non-secret coordinates. The
image must already exist at an immutable digest and the runtime service account must
already exist.

Public invocation defaults to `false`. Setting it to `true` is an IAM decision and
requires explicit owner approval before a real plan.

See `EXECUTION_PACKET.md` for the provider-stage preflight, expected diff, exact
commands, evidence, stop conditions, smoke test, and rollback procedure.
