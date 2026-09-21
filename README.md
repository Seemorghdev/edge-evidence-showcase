# Edge Evidence — Project 03 Integrated Showcase

This repository is the **generated presentation and synthetic integration surface** for
the Edge Evidence portfolio. It is not the implementation authority for processor,
replication, the reference platform, infrastructure, or operations.

## Evaluate in 2 minutes

**What Project 03 demonstrates.** The portfolio separates deterministic evidence
processing, immutable replication, application/cloud integration, infrastructure desired
state, controlled operations, and public presentation. This Showcase itself proves the
synthetic processor/replication path: separate worker environments, verified byte-for-byte
handoff, independent replication readback, and replay with no new writes.

**What is separate cloud evidence.** The current accepted application/cloud path is the
Reference Platform's bounded public Cloud Run recruiter deployment: three synthetic/read-only
services with browser/client verification and exact-origin CORS. This Showcase also has a
current owner-authorized Heroku recruiter deployment using one Basic `web` dyno, with HTTPS
smoke and browser acceptance verified. The earlier GKE observation and Showcase Cloud Run
deployment remain retained historical evidence. None of these make this repository deployment
authority, production infrastructure, or persistent evidence authority.

**Fastest local path.** A Codespace or the provided devcontainer is the preferred
zero-friction environment. On a local host, `scripts/setup.sh` requires Python 3.12 or
newer plus `make`, `ffmpeg`, `ffprobe`, and `sqlite3`.

```bash
./scripts/setup.sh
make demo
make inspect
```

A retained source/CI run of this exact generated bundle produced the public-safe sample
below. The result shape and `sha256:` fingerprint format are stable contracts; the exact
fingerprint is **not a universal value across every supported host or toolchain**.
Repeated runs under the same fixed toolchain/environment are expected to produce
byte-identical fingerprint maps:

```json
{
  "proof_class": "integrated_synthetic_processing_and_replication",
  "status": "pass",
  "run_fingerprint": "sha256:16fb934f03eb36557808d8a05934bc890b9d8de220709551ca41330746abdd17",
  "constraints": {
    "network_required": false,
    "credentials_required": false,
    "publication_performed": false
  },
  "invariants": {
    "processor_output_replicated_by_identity": true,
    "replicated_bytes_match_processor_output": true,
    "integrated_replication_replay_is_noop": true
  }
}
```

The same run prints `Edge Evidence integrated synthetic showcase: PASS`; inspect the
machine result at `.demo-output/combined/summary.json`. To prove determinism in the
environment you are evaluating, run two independent demos and compare `make fingerprint`
outputs as shown in [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md). Then continue
with [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`docs/CLAIMS-AND-LIMITATIONS.md`](docs/CLAIMS-AND-LIMITATIONS.md), and
[`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md). No decorative screenshot is added:
the current evidence surfaces are deterministic receipts/JSON plus the GitHub-rendered
Mermaid architecture, not a separate recruiter-facing UI.

## 30-second flagship map

The recruiter-facing hierarchy is intentionally smaller than the repository inventory:

```text
Edge Evidence — flagship
├── Reliable Engine
│   ├── Processor — deterministic processing, checkpoint/recovery, lineage verification, replay-safe behavior
│   └── Replication — immutable replication, collision refusal, independent readback, deterministic convergence
├── Reference Platform — Web UI + Evidence API + Edge Agent; application/product integration
├── Infrastructure — reviewed desired state
├── Operations — controlled execution + evidence governance
└── Showcase — public proof + navigation + reproducibility
```

| Recruiter layer | What it means | Public reviewer path |
| --- | --- | --- |
| Reliable Engine | Processor + Replication: deterministic processing and recovery, lineage verification, replay-safe/idempotent behavior, immutable replication, collision refusal, independent readback, and deterministic convergence | Canonical `edge-evidence-processor` and `edge-evidence-replication` remain **private canonical product** surfaces; [`edge-evidence-processor-worker`](https://github.com/Seemorghdev/edge-evidence-processor-worker) and [`edge-evidence-replication-worker`](https://github.com/Seemorghdev/edge-evidence-replication-worker) are inspectable **legacy generated/export surfaces only** |
| Reference Platform | Application/product layer around deterministic evidence components, packaged as Web UI, Evidence API, and Edge Agent | [Public-safe Reference Platform summary](docs/REFERENCE-PLATFORM.md); `edge-evidence-reference-platform` — private by current architecture decision; public publication is not current work |
| Infrastructure | Reviewed desired state — what platform state should exist | [`edge-evidence-infrastructure`](https://github.com/Seemorghdev/edge-evidence-infrastructure) is the direct public technical surface; desired state does **not** authorize itself to execute |
| Operations | Control-plane and evidence-governance layer for reviewed execution | [Public-safe Operations Control Model](docs/OPERATIONS-CONTROL-MODEL.md); `edge-evidence-operations` — private control/governance surface by current architecture decision |
| Showcase | Public proof, navigation, reproducibility, and claim boundaries | You are here; this repository is presentation/proof, not implementation or execution authority |

Repository visibility describes **publication state only**. It is not a readiness,
completeness, production, or authority signal: private does not mean unready, and public
does not make a repository cloud/deployment authority.

### Legacy generated worker exports

The public Processor and Replication worker repositories are inspection windows into the
Reliable Engine's generated proof surfaces. They are **legacy generated/export surfaces**,
not canonical authorities and not separate portfolio projects. This Showcase still bundles
their exact generated worker products for the integrated synthetic demo; canonical
implementation authority remains with the private Processor and Replication repositories,
not the worker exports or the copied `components/` trees.

## What Project 03 demonstrates

The portfolio demonstrates a deliberately separated evidence pipeline rather than one
large process with hidden authority:

1. the **processor** freezes eligible work, resumes deterministic checkpoints, verifies
   derived output and lineage, and remains safe under exact replay;
2. **replication** adopts or immutably creates target objects, independently reads them
   back, refuses collisions, and converges safely under exact replay;
3. the **reference platform** composes the separate application and cloud-integration
   services that consume release-pinned processor/replication contracts and outputs;
4. **infrastructure** is the separate desired-state surface: it describes what reviewed
   cloud/platform state should exist, not who is authorized to change it;
5. **operations** is the separate controlled-execution/evidence-governance surface: it
   describes how reviewed humans or automation may inspect or change state under explicit
   controls, without becoming infrastructure desired-state authority;
6. this **showcase** proves a verified synthetic processor report can cross the process
   boundary into replication byte-for-byte without importing both worker runtimes into
   one Python process, and gives reviewers one place to navigate the portfolio.

The demos here are synthetic. They are useful because they exercise the real exported
worker behavior and failure boundaries without publishing private evidence, credentials,
camera details, provider coordinates, or persistent evidence authority.

## Authority model and provenance

This showcase is generated from private canonical source (identity withheld). Authoritative presentation
corrections are made at that source and regenerated here. `BUNDLE_MANIFEST.json` and the
component `EXPORT_PROVENANCE.json` files bind the generated worker candidates and their
public-safe content identities.

The canonical six-surface portfolio map is **navigation**, not bundle composition.
`PUBLIC_COMPONENTS.json` keeps those concepts separate: the bundled legacy generated
worker exports remain the runnable demo components, while the canonical surface inventory
records current repository names and publication visibility.

The generated bundle contains no credentials, private proof payloads, camera source, or
persistent-authority configuration. Deployment adapters remain manual and require a
separately approved credentialed executor.

## Local setup details

`setup.sh` verifies the generated component digests and installs the workers into separate
virtual environments:

```text
.venv/processor/
.venv/replication/
```

The showcase orchestrator communicates with them only through subprocess status, JSON
receipts, filesystem paths, and SHA-256 identities. Run `make test` for the full local test
tour and `make clean` when finished; cleanup removes only the guarded `.demo-output` path.

For deeper review, `PUBLIC_CLAIMS.json` is the machine-readable public claim boundary and
`PUBLIC_COMPONENTS.json` separates bundled generated components from canonical portfolio
navigation.

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

## Codespaces direct HTTP demonstration

The preferred Codespace/devcontainer does **not** require Docker or `curl` for this deeper
reviewer path. Port `8080` is declared as **Showcase HTTP** in the devcontainer. After
setup, start the checked-in read-only service with stdin detached from the interactive
terminal, then probe it with the Python standard library:

```bash
PORT=8080 .venv/showcase/bin/python scripts/serve_showcase.py \
  </dev/null >/tmp/showcase-http.out 2>/tmp/showcase-http.err &
pid=$!

.venv/showcase/bin/python - <<'PY'
import json
from urllib.request import urlopen


def get(path):
    with urlopen("http://127.0.0.1:8080" + path, timeout=120) as response:
        return json.load(response)


print(get("/healthz"))
print(get("/readyz"))
first = get("/api/demo")
second = get("/api/demo")
print({"status": first["status"], "cached": first["cached"]})
print({"status": second["status"], "cached": second["cached"]})
PY

kill "$pid"
wait "$pid" 2>/dev/null || true
```

Expected semantics are health `ok`, readiness `ready`, a first demo response with
`status=pass` and `cached=false`, then a second `status=pass` response with `cached=true`.
When using GitHub Codespaces, the Ports panel should expose the declared **Showcase HTTP**
port `8080`; opening it in a browser shows the public service document at `/`, and
`/api/demo` exposes the same bounded synthetic summary. The adapter accepts no request
body, query input, evidence, or camera source.

## Container demonstration

On a **Docker-capable host**, build the canonical runtime image from the generated bundle.
Docker is not bundled into the preferred Codespace merely for this walkthrough. The
default container command is a read-only HTTP adapter that accepts no body, query input,
evidence, or camera source:

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

## Cloud evidence — current, historical, and deliberately unclaimed

Cloud evidence is intentionally separated from the local synthetic proof.

**Current Reference Cloud Run recruiter path.** The separate Reference Platform track has
an accepted owner-authorized bounded public Cloud Run deployment of Web UI, Evidence API,
and Edge Agent. Synthetic artifact, health/inspection, exact-origin CORS, automated Firefox
browser, and final provider-readback checks passed. Private provider coordinates and retained
evidence are intentionally not copied here.

**Current Showcase Heroku recruiter path.** This Showcase has an accepted owner-authorized
public-safe Heroku deployment using exactly one Basic `web` dyno, with zero add-ons and no
unexpected process types. HTTPS smoke plus Firefox/browser, console, and network acceptance
passed against the accepted release. The provider-assigned URL is not hard-coded into this
generated source; publishing that exact URL remains a separate presentation choice. This
proves a bounded live evaluator surface, not production availability or persistent evidence
authority.

**Historical evidence retained.** The earlier zero-mutation GKE external-exposure observation
and the bounded authenticated-only Showcase Cloud Run deployment remain valid historical
proof for the states they recorded. They grant no new deployment authority.

**Deliberately not claimed.** Custom-domain/DNS ownership, custom certificate naming,
production availability, performance, scale, SLOs, physical evidence integration, and
persistent hosted evidence authority remain outside the accepted public claim boundary.
Provider-assigned HTTPS was verified for the accepted current live paths; no custom-domain
or production claim is implied.

The retained Cloud Run Terraform and deployment scripts are therefore a **bounded
historical adapter/proof surface**, not the current centerpiece architecture or cloud
authority. Credential-free validation remains available with:

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
- No custom-domain/DNS ownership, custom-certificate, production-availability, performance, or SLO claim.

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
