# Deployment preparation and local executor contract

This directory prepares deployment without carrying credentials or provider identity.
The repository is not an execution authority. A human-approved local credentialed
executor performs provider calls only after the exact coordinates, cost boundary, IAM
decision, image digest, state location, and rollback target are frozen.

## Current stage

The current stage is **service-owned Terraform planning**. No real provider plan,
resource creation, public URL, hosted smoke proof, availability claim, or production
claim is implied by these files.

The public GitHub Actions surface validates syntax, the deployment contract, the
service-owned Cloud Run configuration, mocked Terraform plan tests, and policy
fixtures. It has no OIDC permission, provider secret, provider login, Google API plan,
resource creation, deployment, rollback, or provider smoke step.

The Terraform example and exact local-executor packet are under:

```text
infra/cloud-run/
infra/cloud-run/EXECUTION_PACKET.md
```

## Required local tools

- Bash
- Python 3.12 or newer
- Terraform 1.16.0
- Docker with `linux/amd64` build support
- `gcloud` for an approved Cloud Run execution
- `curl` for an approved Heroku execution and smoke readback

Run the credential-free repository checks first:

```bash
./deploy/preflight.sh --offline
```

The Cloud Run Terraform directory can also be validated without credentials:

```bash
terraform -chdir=infra/cloud-run init -backend=false -input=false
terraform -chdir=infra/cloud-run fmt -check -recursive
terraform -chdir=infra/cloud-run validate
terraform -chdir=infra/cloud-run test -no-color
python3 infra/cloud-run/policy/check_source.py
```

After owner approval and only on the local credentialed executor, run:

```bash
./deploy/preflight.sh
```

The command checks tool presence and configuration names. It does not print tokens,
credential files, account inventories, or full environment dumps.

## Configuration names

The service-owned Terraform packet freezes these non-secret coordinates:

```text
project_id
region
artifact_registry_repository
image_name
image_digest
service_name
service_account_email
allow_public_invocation
```

Cloud Run script execution uses:

```text
GCP_PROJECT_ID
GCP_REGION
GCP_CLOUD_RUN_SERVICE
SHOWCASE_ALLOW_CREATE_CLOUD_RUN_SERVICE
SHOWCASE_ALLOW_PUBLIC_INVOCATION
```

Heroku execution uses:

```text
HEROKU_APP_NAME
HEROKU_API_KEY
HEROKU_REGION
HEROKU_DYNO_SIZE
```

Both provider scripts require:

```text
SHOWCASE_DEPLOYMENT_APPROVED=1
SHOWCASE_DEPLOYMENT_EXECUTOR=local
```

Do not paste values into chat, commit them, attach them to a pull request, upload them
as CI evidence, or include them in logs.

## Image preparation

Build one canonical image and freeze its digest before either provider call:

```bash
docker build --platform linux/amd64 --target runtime \
  --tag edge-evidence-showcase:deploy .
docker image inspect edge-evidence-showcase:deploy \
  --format '{{index .RepoDigests 0}} {{.Id}}'
```

A registry-qualified immutable digest is required for the execution packet. Cloud Run
and Heroku must receive the same image bytes.

## Cloud Run execution boundary

`infra/cloud-run/` manages only the named Cloud Run v2 service and the optional
non-authoritative `allUsers` invoker member. It does not own project, billing, API,
repository, image, runtime identity, state backend, network, domain, or observability
resources. Its real plan and apply commands are documented but intentionally not run by
public CI.

`deploy/cloud-run.sh IMAGE_URI` remains a guarded imperative alternative. It deploys
only after the two execution guards are set. It reads the project, region, and service
from environment variables. If the service does not already exist, it stops unless
`SHOWCASE_ALLOW_CREATE_CLOUD_RUN_SERVICE=1` is present in the approved packet.
Unauthenticated invocation is not changed unless
`SHOWCASE_ALLOW_PUBLIC_INVOCATION=1` is explicitly approved.

Before execution, retain:

```bash
gcloud run services describe "$GCP_CLOUD_RUN_SERVICE" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --format='yaml(metadata.name,status.latestReadyRevisionName,status.traffic,status.url)'
```

After execution, repeat the readback and record the new revision, image digest, traffic,
URL, health result, and rollback command.

## Heroku execution boundary

`deploy/heroku.sh LOCAL_IMAGE` requires an already-created container-stack app. It does
not create an app. App creation, region, plan, and spending limit are separate owner
decisions.

Before execution, retain the current app and release identity without logging the API
key:

```bash
curl --fail --silent --show-error \
  --header "Authorization: Bearer ${HEROKU_API_KEY}" \
  --header 'Accept: application/vnd.heroku+json; version=3' \
  "https://api.heroku.com/apps/${HEROKU_APP_NAME}/releases" \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r[-1]["id"], r[-1]["version"])'
```

Rollback uses the exact previous release identified in the execution packet. Perform
it with the approved local tooling, then read back the current release and run the same
smoke test. Never include the authorization header or token in retained evidence.

## Live smoke and evidence

After both URLs are approved and reachable:

```bash
python3 scripts/smoke_live.py \
  --url "$CLOUD_RUN_URL" \
  --url "$HEROKU_URL" \
  | tee deployment-smoke.json
sha256sum deployment-smoke.json
```

The receipt must bind the source commit/tree, immutable image digest, provider resource
identities, previous and new revisions/releases, URLs, plan and smoke digests, cost
boundary, and rollback readback. Sanitize account identifiers and any provider
coordinates not approved for public disclosure.

## Stop conditions

Stop before a provider plan or write when any approved coordinate changed, the image
digest is not exact, state retention is unresolved, a required resource would be
created without approval, public IAM would change without approval, the plan contains
deletion/replacement or resources outside the allowlist, the cost boundary is absent,
rollback identity is absent, or a command would expose a credential.
