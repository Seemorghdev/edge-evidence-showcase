#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
for tool in ffmpeg ffprobe make; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'required tool not found: %s\n' "$tool" >&2
    exit 1
  fi
done

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON" -m venv .venv
fi

export PIP_DISABLE_PIP_VERSION_CHECK=1
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pip install --no-deps -e './optional/processor-pilot'
.venv/bin/python -m pip check

printf 'processor-worker environment ready\n'
printf '  python: %s\n' "$(.venv/bin/python --version 2>&1)"
printf '  ffmpeg: %s\n' "$(ffmpeg -version | head -n 1)"
printf '  next: make demo\n'
