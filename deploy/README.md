# Deployment preparation and local executor contract

This directory prepares deployment without carrying credentials or provider identity.
The repository is not an execution authority. A human-approved local credentialed
executor performs provider calls only after the exact coordinates, cost boundary, IAM
decision, image digest, and rollback target are frozen.

## Current stage

The current stage is **credential-free planning**. No live deployment, resource
creation, public URL, hosted smoke proof, availability claim, or production claim is
implied by these files.

The public GitHub Actions surface validates syntax and this contract only. It has no
OIDC permission, provider secret, provider login, resource creation, deployment, or
rollback step.

## Required local tools

- Bash
- Python 3.12 or newer
- Docker with `linux/amd64` build support
- `gcloud` for the approved Cloud Run execution
- `curl` for the approved Heroku execution and smoke readback

Run the offline repository checks first:

```bash
./deploy/preflight.sh --offline
```

After owner approval and only on the local credentialed executor, run:

```bash
./deploy/preflight.sh
```

The command checks tool presence and configuration names. It does not print tokens,
credential files, account inventories, or full environment dumps.

## Configuration names

Cloud Run execution uses:

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

`deploy/cloud-run.sh IMAGE_URI` deploys only after the two execution guards are set.
It reads the project, region, and service from environment variables. If the service
does not already exist, it stops unless
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

Rollback uses an exact previously recorded ready revision:

```bash
gcloud run services update-traffic "$GCP_CLOUD_RUN_SERVICE" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --to-revisions="PREVIOUS_REVISION=100"
```

Do not guess a revision name. Read back traffic and health after rollback.

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
identities, previous and new revisions/releases, URLs, smoke digest, cost boundary, and
rollback readback. Sanitize account identifiers and any provider coordinates not
approved for public disclosure.

## Stop conditions

Stop before a provider write when any approved coordinate changed, the image digest is
not exact, a required resource would be created without approval, public IAM would
change without approval, the cost boundary is absent, rollback identity is absent, or
a command would expose a credential.
