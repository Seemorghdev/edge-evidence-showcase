"""CLI for the bounded processor worker."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from apps._cli import foundation_parser
from apps.processor_worker import worker


def build_parser() -> argparse.ArgumentParser:
    parser = foundation_parser(
        "processor-worker",
        "Bounded catch-up worker for deterministic local processing.",
    )
    commands = parser.add_subparsers(dest="command")
    run = commands.add_parser("run")
    run.add_argument("--database", required=True, type=Path)
    run.add_argument("--spool-root", required=True, type=Path)
    return parser


def _emit(payload: dict[str, object], *, error: bool = False) -> None:
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ),
        file=sys.stderr if error else sys.stdout,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 0
    try:
        summary = worker.run(args.database, args.spool_root)
    except worker.ProcessorWorkerError as exc:
        _emit({"status": "error", "finding": exc.finding}, error=True)
        return exc.code
    _emit(summary.public())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())