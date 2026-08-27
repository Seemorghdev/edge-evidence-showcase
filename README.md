# Edge Evidence Integrated Showcase

This generated product runs the generated processor worker and generated replication
worker as separately installed local packages. It demonstrates a verified processor
report flowing into deterministic local replication without importing both workers
into one Python process.

The showcase is generated from private canonical source (identity withheld). Authoritative corrections are
upstream-first. The generated bundle contains no credentials, private proof material,
camera source, or persistent-authority configuration. Its deployment adapters remain
manual and require a separately approved local credentialed executor.

## One-command experience

In a Codespace or the provided development container:

```bash
./scripts/setup.sh
make demo
make inspect
make test
make clean
```

`setup.sh` verifies the generated component digests and installs the two worker
products into separate virtual environments:

```text
.venv/processor/
.venv/replication/
```

The showcase orchestrator communicates with them only through subprocess status,
JSON receipts, filesystem paths, and SHA-256 identities.

## What `make demo` proves

The processor product runs its normal, committed-resume, and busy-lock reliability
scenarios. The replication product runs its target lifecycle, adoption, immutable
create, readback, cleanup, rerun, and collision-refusal scenarios. The integrated
handoff then takes the processor's verified derived report bytes and publishes those
same bytes into a fresh local replication target, independently verifies the target,
and proves an exact rerun performs no new write.

All state remains inspectable under `.demo-output/`:

```text
.demo-output/
├── processor/
├── replication/
├── handoff/
└── combined/
```

`make inspect` is read-only. `make clean` removes only a guarded `.demo-output` path
inside this repository.

## Container execution

Build the canonical runtime image from the generated bundle. The default command is a
read-only HTTP adapter that accepts no body, query input, evidence, or camera source:

```bash
docker build --target runtime -t edge-evidence-showcase:local .
docker run --rm --publish 127.0.0.1:8080:8080 \
  --env PORT=8080 \
  --cpus 1 --memory 512m \
  edge-evidence-showcase:local
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/demo
```

Each instance runs the deterministic synthetic workload at most once, caches only its
public summary in memory, and removes its temporary output. The original batch-style
container commands remain available explicitly:

```bash
docker run --rm --network none \
  --mount type=bind,src="$PWD/.demo-output",dst=/workspace/showcase/.demo-output \
  edge-evidence-showcase:local demo
```

The runtime uses a non-root user. Container-local files, SQLite databases, and
in-memory summaries are demonstration state only and are not persistent evidence
authority.

## Credential-free deployment preparation

`.github/workflows/deployment-readiness.yml` validates the sanitized deployment
contract, guarded scripts, shell syntax, and offline preflight. It has read-only
repository permission and performs no provider authentication, image push, resource
creation, IAM change, deployment, rollback, or provider smoke.

The Cloud Run and Heroku commands are retained under `deploy/` for an approved local
credentialed executor. Both scripts require explicit approval and local-executor guard
variables. Cloud Run additionally requires an immutable image digest and separate
creation/public-invocation guards. Heroku requires a pre-existing container-stack app
and never creates one.

Run the credential-free checks with:

```bash
python3 scripts/validate_deployment_contract.py
./deploy/preflight.sh --offline
```

See `deploy/README.md` for configuration names, preflight, image identity, exact smoke,
evidence, stop conditions, and rollback procedures. Live URLs and deployment badges
are intentionally absent because no hosted deployment has been executed or verified.

## Boundaries

- Synthetic inputs only.
- No request-supplied evidence or camera access.
- No credentials or external provider call from the synthetic workload.
- No credential-bearing provider execution from public GitHub Actions.
- No ADK execution, model call, or autonomous loop.
- No Ollama.
- No production, availability, performance, fleet, or physical-storage claim.
- No persistent hosted evidence authority.
- GKE, Helm, Datadog, custom domains, and physical integration are out of scope.

## Security and contributions

Security-sensitive reports must use **GitHub Private Vulnerability Reporting / GitHub
Security Advisories**, not public issues. Do not disclose credentials, provider
coordinates, retained evidence, or personal data. See `SECURITY.md` and
`CONTRIBUTING.md`.

## License and control boundary

License: **MIT**.

The presence of deployment contracts or scripts does not authorize third-party
provider writes. Provider credentials, billable resources, IAM/public access, exact
coordinates, cost ceilings, and live execution remain separate owner-approved actions
performed only by the approved local credentialed executor.
