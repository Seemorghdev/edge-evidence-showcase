# Edge Evidence Showcase

The public synthetic integration and reproducibility surface for the Edge Evidence portfolio.

[![CI](https://github.com/Seemorghdev/edge-evidence-showcase/actions/workflows/ci.yml/badge.svg)](https://github.com/Seemorghdev/edge-evidence-showcase/actions/workflows/ci.yml)

**Status.** Built: a Visual Gateway for three synthetic records and a separate retained processing-and-replication result. Evidence: the integrated demo passes locally; the latest recorded CI run passed on Python 3.12 and 3.14 (20 October 2026). Limits: synthetic inputs only; this repository is not production infrastructure or persistent evidence authority.

## Quick-start

Requirements: Python 3.12 or newer, `make`, `ffmpeg`, `ffprobe`, and `sqlite3`.

The setup script installs offline into three local virtual environments; the loop below creates them with the build tools the script expects.

```bash
for name in showcase processor replication; do
  python3 -m venv --copies ".venv/${name}"
  ".venv/${name}/bin/python" -m pip install --disable-pip-version-check "setuptools==82.0.1" "pytest==8.4.1"
done
bash scripts/setup.sh
make demo
make inspect
make test
```

Expected results from the tested Python 3.12.13 setup:

- `make demo`: `Edge Evidence integrated synthetic showcase: PASS`.
- `make inspect`: reports passing processor and replication summaries; combined summary at `.demo-output/combined/summary.json`.
- `make test`: 21 showcase, 51 processor, and 57 replication tests passed (one optional test deselected).

## Tests

`make test`: 129 passed. CI: [`integrated-showcase-ci`](https://github.com/Seemorghdev/edge-evidence-showcase/actions/workflows/ci.yml) tests Python 3.12 and 3.14. The latest recorded default-branch run passed on 20 October 2026.

## How it fits

Part of [Edge Evidence](https://mehridian.tech/projects/edge-evidence). This repository brings generated components together for a synthetic demo; it does not own their canonical implementation. See the [portfolio overview](docs/portfolio-overview.md) for the architecture and evidence details. Technical docs: [Architecture](docs/ARCHITECTURE.md), [claims and limitations](docs/CLAIMS-AND-LIMITATIONS.md), and [reproducibility](docs/REPRODUCIBILITY.md).

## Licence

MIT. See `LICENSE`.
