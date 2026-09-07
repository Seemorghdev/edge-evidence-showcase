# Edge Evidence — Project 03 Integrated Showcase

This repository is the **generated presentation and synthetic integration surface** for
the Edge Evidence portfolio. It is not the implementation authority for processor,
replication, or the reference platform.

## 30-second portfolio map

| Surface | What it owns | Where to go |
| --- | --- | --- |
| Processor worker | Deterministic bounded processing catch-up over existing SQLite/filesystem authority | [`edge-evidence-processor-worker`](https://github.com/Seemorghdev/edge-evidence-processor-worker) |
| Replication worker | Deterministic convergence of finalized immutable objects into an already-bound replica target | [`edge-evidence-replication-worker`](https://github.com/Seemorghdev/edge-evidence-replication-worker) |
| Reference platform | End-to-end services, integration, Terraform, Kubernetes/GKE delivery, and cloud evidence | `edge-evidence-reference-platform` — currently private; public publication is pending |
| This showcase | Synthetic processor → replication handoff, runnable demos, claim boundaries, and recruiter-facing navigation | You are here |

The two public worker repositories are themselves generated products from private
canonical sources. Authoritative worker corrections remain upstream-first. This bundle
includes exact generated worker products for the integrated synthetic demo; do not treat
`components/` as a fourth implementation authority.

## What Project 03 demonstrates

The portfolio demonstrates a deliberately separated evidence pipeline rather than one
large process with hidden authority:

1. the **processor** freezes eligible work, resumes deterministic checkpoints, verifies
   derived output and lineage, and remains safe under exact replay;
2. the **replication worker** adopts or immutably creates target objects, independently
   reads them back, refuses collisions, and converges safely under exact replay;
3. this **showcase** proves a verified synthetic processor report can cross the process
   boundary into replication byte-for-byte without importing both worker runtimes into
   one Python process;
4. the **reference platform** is the separate application/cloud integration track. Its
   accepted evidence includes bounded Cloud Run proof and a later GKE external-exposure
   observation, while final public DNS/HTTPS naming remains pending.

The demos here are synthetic. They are useful because they exercise the real exported
worker behavior and failure boundaries without publishing private evidence, credentials,
camera details, provider coordinates, or persistent evidence authority.

## Authority model and provenance

This showcase is generated from private canonical source (identity withheld). Authoritative presentation
corrections are made at that source and regenerated here. `BUNDLE_MANIFEST.json` and the
component `EXPORT_PROVENANCE.json` files bind the generated worker candidates and their
public-safe content identities.

The generated bundle contains no credentials, private proof payloads, camera source, or
persistent-authority configuration. Deployment adapters remain manual and require a
separately approved credentialed executor.

## Fast local tour

In a Codespace or the provided development container:

```bash
./scripts/setup.sh
make demo
make inspect
make test
make clean
```

`setup.sh` verifies the generated component digests and installs the workers into
separate virtual environments:

```text
.venv/processor/
.venv/replication/
```

The showcase orchestrator communicates with them only through subprocess status, JSON
receipts, filesystem paths, and SHA-256 identities.

For a technical walkthrough, start with:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how processor, replication, showcase,
  and the reference platform relate;
- [`docs/CLAIMS-AND-LIMITATIONS.md`](docs/CLAIMS-AND-LIMITATIONS.md) — what the demos and
  cloud evidence do and do not prove;
- [`PUBLIC_CLAIMS.json`](PUBLIC_CLAIMS.json) — machine-readable public claim boundary;
- [`PUBLIC_COMPONENTS.json`](PUBLIC_COMPONENTS.json) — generated component inventory;
- [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md) — bundle verification and
  deterministic regeneration expectations.

## What `make demo` proves

The processor product runs normal, committed-resume, and busy-lock reliability
scenarios. The replication product runs target lifecycle, adoption, immutable create,
readback, cleanup, rerun, and collision-refusal scenarios. The integrated handoff then
takes the processor's verified derived report bytes and publishes those same bytes into
a fresh local replication target, independently verifies the target, and proves an exact
rerun performs no new write.

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

## Container demonstration

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
public summary in memory, and removes its temporary output. Batch-style execution remains
available explicitly:

```bash
docker run --rm --network none \
  --mount type=bind,src="$PWD/.demo-output",dst=/workspace/showcase/.demo-output \
  edge-evidence-showcase:local demo
```

Container-local files, SQLite databases, and in-memory summaries are demonstration state
only and are not persistent evidence authority.

## Cloud evidence — proven versus pending

Cloud evidence is intentionally separated from the local synthetic proof.

**Proven Cloud Run boundary.** An owner-authorized, authenticated-only Cloud Run deployment
in a disposable environment of the exact immutable showcase image completed provider
readback and the synthetic smoke path. The live URL, project, identity, state, and retained
evidence coordinates remain private. This proves a bounded deployment/smoke event, not
production availability or persistent hosted evidence authority.

**Proven GKE boundary.** The separate reference-platform evidence track has an accepted,
zero-mutation GKE external-exposure observation that verified the reviewed synthetic
three-service workload and bounded same-origin HTTP journey under a stable provider state.
Private provider coordinates and retained evidence are intentionally not copied here.

**Still pending.** Stable public-address ownership/binding, final DNS naming,
ManagedCertificate/TLS/HTTPS transition, production availability, performance, scale,
SLOs, and physical evidence integration are outside the accepted public claim boundary.
No temporary endpoint is published from this repository.

The Cloud Run Terraform and deployment scripts in this repository are therefore best read
as a **bounded showcase adapter and historical proof surface**, not as the current cloud
architecture authority. Credential-free validation remains available with:

```bash
python3 scripts/validate_deployment_contract.py
./deploy/preflight.sh --offline
terraform -chdir=infra/cloud-run init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/cloud-run validate
terraform -chdir=infra/cloud-run test -no-color
python3 infra/cloud-run/policy/check_source.py
```

Public GitHub Actions perform no provider authentication, live Terraform plan/apply,
image push, resource creation, IAM change, deployment, rollback, or provider smoke.

## Engineering signals worth reviewing

- deterministic, idempotent worker state transitions with explicit replay semantics;
- checkpointed processor recovery and fail-closed lock behavior;
- immutable replication with independent readback and collision refusal;
- cross-process integration through receipts, paths, sizes, and digests rather than
  shared runtime imports;
- generated-product provenance with upstream-first authority and reproducible candidates;
- bounded cloud-operation contracts that separate review, authorization, execution,
  verification, and retained evidence.

## Claim boundary

- Synthetic inputs only in this public showcase.
- No request-supplied evidence or camera access.
- No credentials or external provider call from the synthetic workload.
- No credential-bearing provider execution from public GitHub Actions.
- No real Terraform provider plan or apply from public GitHub Actions.
- No ADK execution, model call, autonomous loop, or Ollama claim here.
- No production, availability, performance, fleet, SLO, or physical-storage claim.
- No persistent hosted evidence authority.
- No publication of private topology, provider coordinates, retained evidence payloads,
  footage, camera details, credentials, or Terraform state.
- Final DNS/HTTPS naming remains pending.

## Security and contributions

Security-sensitive reports must use **GitHub Private Vulnerability Reporting / GitHub
Security Advisories**, not public issues. Do not disclose credentials, provider
coordinates, retained evidence, or personal data. See `SECURITY.md` and
`CONTRIBUTING.md`.

## License and control boundary

License: **MIT**.

The presence of deployment contracts, Terraform, Kubernetes/GKE evidence references, or
scripts does not authorize third-party provider writes. Credentials, billable resources,
IAM/public access, exact coordinates, state ownership, and live execution remain separate
owner-approved actions.
