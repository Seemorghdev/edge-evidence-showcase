#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PYTHON=${PYTHON:-python}

"$PYTHON" -m pip install --disable-pip-version-check -e '.[dev]'

printf '%s\n' \
  'replication-worker development environment is ready.' \
  'Run: make demo' \
  'Then: make inspect' \
  'Tests: make test'
