"""Command-line entry point for the optional read-only processor pilot."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from packages.agent_contracts.canonical import canonical_json

from .pilot import ProcessorPilotError, SQLiteProcessorReadTool, run_processor_pilot


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="processor-pilot",
        description="Inspect, classify, explain, and propose without mutation.",
    )
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument(
        "--canonical-commit",
        required=True,
        help="Must match the immutable canonical commit embedded in this product.",
    )
    parser.add_argument(
        "--authority-instance",
        default="local-processor-authority",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = run_processor_pilot(
            SQLiteProcessorReadTool(args.database),
            canonical_commit=args.canonical_commit,
            authority_instance=args.authority_instance,
        )
    except ProcessorPilotError as exc:
        parser.error(exc.finding)
    print(canonical_json(result.public()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
