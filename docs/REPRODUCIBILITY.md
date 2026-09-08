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

For the bounded HTTP surface:

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
