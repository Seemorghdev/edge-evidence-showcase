# Reproducibility

`BUNDLE_MANIFEST.json` binds the generated processor and replication component path
counts and public-safe content-tree SHA-256 values. `scripts/verify_bundle.py` checks
those identities before installation.

For a local deterministic comparison:

```bash
./scripts/setup.sh
make demo OUTPUT_ROOT=.demo-output-a
make fingerprint OUTPUT_ROOT=.demo-output-a > /tmp/a.json
make demo OUTPUT_ROOT=.demo-output-b
make fingerprint OUTPUT_ROOT=.demo-output-b > /tmp/b.json
diff -u /tmp/a.json /tmp/b.json
```

The fingerprint excludes SQLite databases, synthetic MP4 files, and lock files. Each
worker is responsible for validating its own authoritative state semantics; the
showcase compares stable receipts, summaries, manifests, and generated report/target
hashes.

All demonstration execution is local and network-free. Package installation uses only
the generated bundle and the already available build/test tooling in the selected
Python environment.
