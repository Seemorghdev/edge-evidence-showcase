#!/usr/bin/env bash
set -euo pipefail

command_name="${1:-demo}"
shift || true

case "${command_name}" in
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
