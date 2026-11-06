# Edge Evidence Showcase

The public synthetic integration and reproducibility surface for the Edge Evidence portfolio.

[![CI](https://github.com/Seemorghdev/edge-evidence-showcase/actions/workflows/ci.yml/badge.svg)](https://github.com/Seemorghdev/edge-evidence-showcase/actions/workflows/ci.yml)

**Status.** Built: a Visual Gateway for three synthetic records and a separate retained processing-and-replication result. Evidence: the integrated demo passes locally; the latest recorded CI run passed on Python 3.12 and 3.14 (20 October 2026). Limits: synthetic inputs only; this repository is not production infrastructure or persistent evidence authority.

## Quick-start

Needs Python 3.12 or newer with working `venv`/`ensurepip`, `make`, `ffmpeg`, `ffprobe` and `sqlite3`. The setup script uses `--no-build-isolation`, so the selected Python must also have `setuptools==82.0.1` and `pytest==8.4.1` available to it. Use an install whose `venv` works and pass its resolved interpreter path; the PATH-selected Python 3.12.14 command failed locally, while its resolved interpreter path passed. Python 3.13.7 on the tested local install also aborted while creating a venv.

```bash
TOOLS="$(mktemp -d)"
trap 'rm -rf "$TOOLS"' EXIT
python3.12 -m pip install --target "$TOOLS" "setuptools==82.0.1" "pytest==8.4.1"
export PYTHONPATH="$TOOLS${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="$(python3.12 -c 'import pathlib, sys; print(pathlib.Path(sys.executable).resolve())')" bash scripts/setup.sh
make demo       # expect: Edge Evidence integrated synthetic showcase: PASS
make inspect    # read-only summary of the retained local result
make test       # expect 129 passing tests on the tested Python 3.12 setup
```

## Tests

`make test`: 129 passed in the local Python 3.12.14 check. CI: [`integrated-showcase-ci`](https://github.com/Seemorghdev/edge-evidence-showcase/actions/workflows/ci.yml) tests Python 3.12 and 3.14. The latest recorded default-branch run passed on 20 October 2026.

## How it fits

Part of [Edge Evidence](https://mehridian.tech/projects/edge-evidence). This repository brings generated components together for a synthetic demo; it does not own their canonical implementation. See the [portfolio overview](docs/portfolio-overview.md) for the architecture and evidence details. Technical docs: [Architecture](docs/ARCHITECTURE.md), [claims and limitations](docs/CLAIMS-AND-LIMITATIONS.md), and [reproducibility](docs/REPRODUCIBILITY.md).

## Licence

MIT. See `LICENSE`.
