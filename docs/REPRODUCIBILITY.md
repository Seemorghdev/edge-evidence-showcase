# Reproducibility

`BUNDLE_MANIFEST.json` binds the generated processor and replication component path
counts and public-safe content-tree SHA-256 values. `scripts/verify_bundle.py` checks
those identities before installation.

Those bundled components are the legacy generated worker/export products used by the
runnable synthetic demo. They are deliberately separate from the canonical six-surface
portfolio navigation recorded in `PUBLIC_COMPONENTS.json`. A presentation-only navigation
change must not silently change component bytes, component content-tree identities, or
`BUNDLE_MANIFEST.json`.

For a local deterministic comparison:

```bash
./scripts/setup.sh
make demo OUTPUT_ROOT=.demo-output-a
make fingerprint OUTPUT_ROOT=.demo-output-a > /tmp/a.json
make demo OUTPUT_ROOT=.demo-output-b
make fingerprint OUTPUT_ROOT=.demo-output-b > /tmp/b.json
diff -u /tmp/a.json /tmp/b.json
```

Repeated demos under the same fixed toolchain/environment are expected to produce
byte-identical fingerprint maps. The exact retained source/CI `run_fingerprint` shown in
the README is one public evidence sample, **not a universal constant across every
supported host or toolchain**. Compare exact fingerprints across environments only when
the relevant immutable adapter/build environment is intentionally held fixed; otherwise
compare the documented proof shape, invariants, and same-environment identity result.

For the direct Codespaces/devcontainer HTTP surface, Docker and `curl` are not required.
Port `8080` is declared as **Showcase HTTP** in `.devcontainer/devcontainer.json`. Start
the checked-in service with stdin detached from the interactive shell and probe it with
the Python standard library:

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

Expected semantics are health `ok`, readiness `ready`, first demo `status=pass` with
`cached=false`, and second demo `status=pass` with `cached=true`. In GitHub Codespaces,
the Ports panel should expose the declared **Showcase HTTP** port `8080`; the browser root
returns the public service document and `/api/demo` returns the same bounded synthetic
summary.

For the containerized HTTP surface, use a **Docker-capable host**. Docker is not bundled
into the preferred Codespace solely for this walkthrough:

```bash
docker build --target runtime -t edge-evidence-showcase:local .
docker run --rm -d --name edge-evidence-showcase \
  -p 127.0.0.1:8080:8080 -e PORT=8080 \
  --cpus 1 --memory 512m edge-evidence-showcase:local
python3 scripts/smoke_live.py --url http://127.0.0.1:8080 --allow-http
docker rm -f edge-evidence-showcase
```

The fingerprint excludes SQLite databases, synthetic MP4 files, and lock files. Each
worker is responsible for validating its own authoritative state semantics; the
showcase compares stable receipts, summaries, manifests, and generated report/target
hashes.

The retained Cloud Run/Heroku smoke parity path is **historical and bounded**. When that
adapter-compatibility path is exercised, the public smoke tool requires the adapters to
return the same stable synthetic run fingerprint. That parity check does not make either
adapter the current centerpiece architecture, does not publish a permanent endpoint, and
does not grant deployment authority. The current accepted application/cloud observation
is the separate Reference Platform GKE evidence track described in
`docs/CLAIMS-AND-LIMITATIONS.md`.

The synthetic workload itself is network-free and accepts no request input. Package
installation uses only the generated bundle and the already available build/test
tooling in the selected Python environment.

For generated-source consistency, authoritative presentation corrections are made
upstream first and projected through the Showcase exporter. Reviewers should compare the
generated candidate with the downstream repository and confirm that a navigation-only
change touches only the expected presentation/test files while the bundled component
trees and manifest remain unchanged.
