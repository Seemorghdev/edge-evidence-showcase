#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

"${PYTHON}" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or newer is required")
PY

"${PYTHON}" "${ROOT}/scripts/verify_bundle.py"

create_environment() {
  local name="$1"
  local source="$2"
  local environment="${ROOT}/.venv/${name}"

  if [[ ! -x "${environment}/bin/python" ]]; then
    "${PYTHON}" -m venv --system-site-packages "${environment}"
  fi
  "${environment}/bin/python" -m pip install \
    --no-index \
    --no-deps \
    --no-build-isolation \
    --disable-pip-version-check \
    -e "${source}"
}

create_environment showcase "${ROOT}"
create_environment processor "${ROOT}/components/processor-worker"
create_environment replication "${ROOT}/components/replication-worker"

for tool in make ffmpeg ffprobe sqlite3; do
  command -v "${tool}" >/dev/null 2>&1 || {
    echo "required local tool is missing: ${tool}" >&2
    exit 2
  }
done

printf '%s\n' \
  "showcase environment: ${ROOT}/.venv/showcase" \
  "processor environment: ${ROOT}/.venv/processor" \
  "replication environment: ${ROOT}/.venv/replication" \
  "setup complete; run 'make demo'"
