# Edge Evidence Integrated Showcase

This generated product runs the generated processor worker and generated replication
worker as separately installed local packages. It demonstrates a verified processor
report flowing into deterministic local replication without importing both workers
into one Python process.

The showcase is generated from private canonical source (identity withheld). Authoritative corrections are
upstream-first. The generated bundle contains no credentials, provider coordinates,
private proof material, deployment configuration, or publication authority.

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

Build the canonical runtime image from the generated bundle:

```bash
docker build --target runtime -t edge-evidence-showcase:local .
docker run --rm --network none \
  --mount type=bind,src="$PWD/.demo-output",dst=/workspace/showcase/.demo-output \
  edge-evidence-showcase:local demo
```

The runtime uses a non-root user. Container-local files and SQLite databases are
demonstration state only and are not persistent evidence authority.

## Boundaries

- Synthetic local inputs only.
- No network during the demonstration.
- No credentials or provider calls.
- No ADK execution, model call, or autonomous loop.
- No Ollama.
- No cloud deployment or telemetry implementation.
- No production, availability, performance, fleet, or physical-storage claim.
- No public repository creation or mutation.

## Security and contributions

Security-sensitive reports must use **GitHub Private Vulnerability Reporting / GitHub
Security Advisories**, not public issues. Do not disclose credentials, provider
coordinates, retained evidence, or personal data. See `SECURITY.md` and
`CONTRIBUTING.md`.

## License and publication boundary

License: **MIT**.

The presence of a license does not authorize publication. Candidate generation and
`publish-check` remain fail-closed until a separate reviewed change explicitly
authorizes a public write.
