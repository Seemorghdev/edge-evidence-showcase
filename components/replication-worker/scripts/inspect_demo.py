"""Inspect persistent local demo evidence without changing it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _tree(root: Path) -> list[str]:
    return [
        path.relative_to(root).as_posix() + ("/" if path.is_dir() else "")
        for path in sorted(root.rglob("*"))
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(".demo-output"))
    args = parser.parse_args(argv)
    root = args.output_dir.resolve()
    summary_path = root / "summary.json"
    human_path = root / "summary.txt"
    manifest_path = root / "manifest.json"
    for required in (summary_path, human_path, manifest_path):
        if not required.is_file():
            parser.error(f"missing demo evidence: {required.name}; run make demo first")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if summary.get("status") != "pass" or manifest.get("status") != "pass":
        raise SystemExit("demo evidence did not report pass")
    print(human_path.read_text(encoding="utf-8"), end="")
    print("\n.demo-output structure:")
    for item in _tree(root):
        print(f"  {item}")
    print(
        "\nDeterministic evidence digest: "
        + str(manifest["deterministic_files_sha256"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
