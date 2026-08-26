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
hashes. The public smoke tool requires Cloud Run and Heroku to return the same stable
run fingerprint.

The synthetic workload itself is network-free and accepts no request input. Package
installation uses only the generated bundle and the already available build/test
tooling in the selected Python environment.
