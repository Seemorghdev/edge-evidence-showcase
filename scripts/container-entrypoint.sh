#!/usr/bin/env bash
set -euo pipefail

command_name="${1:-serve}"
shift || true

case "${command_name}" in
  serve)
    exec .venv/showcase/bin/python scripts/serve_showcase.py "$@"
    ;;
  demo)
    exec make demo "$@"
    ;;
  test)
    exec make test "$@"
    ;;
  inspect)
    exec make inspect "$@"
    ;;
  fingerprint)
    exec make fingerprint "$@"
    ;;
  clean)
    exec make clean "$@"
    ;;
  bash|sh)
    exec "${command_name}" "$@"
    ;;
  *)
    echo "unsupported showcase command: ${command_name}" >&2
    exit 2
    ;;
esac
