# replication-worker

`replication-worker` is a standalone, bounded replication-convergence product
generated from private canonical source (identity withheld).

This repository is a **generated product**. Authoritative changes are upstream-first
and arrive through deterministic regeneration. Public bytes do not carry the private
repository name, URL, branch, source commit, pull request, source trace, or
operational coordinates.

## Product role

Capture, processing, and replication authority remain separate. This worker owns only
deterministic convergence of finalized immutable evidence objects to one already-bound
replica target:

1. read finalized object identity from existing SQLite/filesystem authority;
2. validate exact target identity and adapter binding;
3. perform worker-owned transient cleanup;
4. use exact adoption or an immutable create;
5. independently read back and verify target bytes;
6. record verified state in canonical SQLite authority.

It does not capture or process media, provision storage, create credentials, change
IAM, choose a target, schedule future work, run as a daemon, or create a second
authority. Azure is not implemented or advertised.

## Codespaces and dev container

Open the generated repository in GitHub Codespaces or VS Code Dev Containers. The
checked-in `.devcontainer/Dockerfile` installs the base package and test tools on the
minimum supported Python line. The same Dockerfile is built by CI.

For a local environment:

```text
bash scripts/setup.sh
make demo
make inspect
make test
```

The demo requires no network, credentials, cloud service, model, or publication
access. It uses only deterministic synthetic bytes, local SQLite authority, and a
local target implementing the canonical mounted-filesystem target contract.

## Deterministic local demo

`make demo` recreates `.demo-output/` and exercises the current canonical CLI,
authority, target adapter, cleanup, immutable publication, exact adoption, readback,
and refusal paths. It proves:

- canonical target creation followed by safe re-adoption with unchanged metadata;
- one exact adoption and one immutable create;
- independent readback with matching identity, size, digest, and authority state;
- removal of a worker-owned transient partial;
- a second identical operation that performs no writes and leaves authority unchanged;
- refusal to overwrite deterministic conflicting bytes.

The terminal output is human-readable. Machine-readable evidence is written to:

```text
.demo-output/summary.json
.demo-output/manifest.json
.demo-output/summary.txt
.demo-output/success/authority.sqlite3
.demo-output/success/spool/
.demo-output/success/target/
.demo-output/collision/authority.sqlite3
.demo-output/collision/spool/
.demo-output/collision/target/
```

Run `make inspect` to print the summary and complete evidence tree. Run `make clean`
to remove generated local state. Re-running `make demo` produces the same synthetic
inputs, summaries, target bytes, and deterministic evidence digest; SQLite files stay
available for inspection but are not treated as byte-for-byte deterministic because
they contain canonical runtime timestamps.

## Authority and state transitions

SQLite and immutable source/target bytes remain authoritative. The worker fails
closed on target-identity mismatch, destination collision, generation-race, corrupt
source/read-back, unsafe paths, unavailable targets, and unsupported exclusive
publication. A collision is never overwritten. An exact rerun creates no new work
and does not rewrite verified bytes.

```text
finalized source
→ discovered replica object
→ PENDING
→ exact adoption or immutable create
→ independent read-back verification
→ VERIFIED
```

## Install and run once

Python 3.11 or newer is required. The base installation has no runtime Python
dependencies and does not install a cloud SDK.

```text
python -m pip install -e '.[dev]'
replication-worker run \
  --database PATH \
  --spool-root PATH \
  --target-config replication.toml
replication-worker verify \
  --database PATH \
  --target-config replication.toml
```

Configuration values are supplied by the operator at runtime. Real target IDs,
mounts, bucket names, prefixes, account identifiers, project identifiers, tokens,
keys, or credential files do not belong in this product.

The optional GCS adapter is installed explicitly:

```text
python -m pip install -e '.[dev,gcs]'
```

Authentication uses provider-standard external credentials. Exported fake-provider
tests require no network or credentials.

## Bounded-agent contract surface

The generated product includes `packages.agent_contracts`, the framework-neutral
contract surface for typed observations, deterministic classifications, bounded
proposals, policy decisions, verification outcomes, and structured receipts.

The replication example is model-free and read-only. It does not execute the worker,
contact a provider, provision storage, change IAM or credentials, mutate SQLite, or
create a second authority.

```text
python -m pytest -q tests/test_agent_contracts.py
```

## Packaging boundary

The export contains the real CLI, provider-neutral core, mounted-filesystem adapter,
optional GCS adapter, schema-v10 migration closure, and focused standalone tests. It
excludes deployment roots, infrastructure, credentials, private topology, private
proof material, and unrelated services.

## Provenance and reproducibility

`EXPORT_PROVENANCE.json` contains only schema/exporter version, component, the
`generated-product/upstream-first` policy, redacted public source label, exact
candidate path count, public-safe content digest, public license,
dependency-boundary identity, and verification commands.

Two candidates from the same exact private head must have identical paths, modes,
bytes, content digest, and deterministic one-commit disposable histories. Exact
private source binding is retained only in private validation records.

## Security

Security-sensitive reports must use **GitHub Private Vulnerability Reporting / GitHub Security Advisories**,
not public issues. Do not disclose credentials, provider coordinates, retained
material, or personal data. See `SECURITY.md`.

## Contributions

General non-security issues may be discussed after private material is removed;
fixes remain upstream-first. See `CONTRIBUTING.md`.

## License and publication boundary

Publication license: **MIT**.

The presence of a license does not authorize publication. The descriptor and
`publish-check` remain fail-closed until a separate reviewed change explicitly
authorizes a public write.
