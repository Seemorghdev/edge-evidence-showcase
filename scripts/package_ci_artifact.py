#!/usr/bin/env python3
"""Create the allowlisted, redacted CI artifact from local showcase output."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_PATHS = (
    "combined/summary.json",
    "combined/summary.txt",
    "processor/summary.json",
    "processor/summary.txt",
    "replication/summary.json",
    "replication/summary.txt",
    "handoff/summary.json",
    "handoff/summary.txt",
)
FORBIDDEN = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"ya29\.[0-9A-Za-z_-]+"),
    re.compile(r"/(?:home|Users|mnt)/[A-Za-z0-9._-]+/"),
    re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])"),
    re.compile(r"\bproject[\s_-]*0?3\b", re.I),
    re.compile(r"\bp03a(?:-r1)?\b", re.I),
    re.compile(r"\bwave[\s_-]+[abc]\b", re.I),
    re.compile(r"\bspec-\d{3,}\b", re.I),
)


class ArtifactFailure(RuntimeError):
    """The requested CI artifact is absent or unsafe."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package(output_root: Path) -> Path:
    root = output_root if output_root.is_absolute() else ROOT / output_root
    root = root.resolve()
    try:
        root.relative_to(ROOT)
    except ValueError as exc:
        raise ArtifactFailure("output root must remain inside the showcase repository") from exc
    artifact = root / "ci-artifact"
    if artifact.exists():
        if artifact.is_symlink() or not artifact.is_dir():
            raise ArtifactFailure("CI artifact destination is unsafe")
        shutil.rmtree(artifact)
    artifact.mkdir(parents=True)

    records: list[dict[str, object]] = []
    for relative in SAFE_PATHS:
        source = root / relative
        if source.is_symlink() or not source.is_file():
            raise ArtifactFailure(f"required safe artifact is absent: {relative}")
        data = source.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactFailure(f"safe artifact is not UTF-8: {relative}") from exc
        for pattern in FORBIDDEN:
            if pattern.search(text):
                raise ArtifactFailure(f"privacy or vocabulary finding in {relative}")
        destination = artifact / relative.replace("/", "-")
        destination.write_bytes(data)
        records.append(
            {
                "source": relative,
                "artifact": destination.name,
                "byte_size": len(data),
                "sha256": _sha(data),
            }
        )

    manifest = {
        "schema_version": 1,
        "status": "pass",
        "scope": "safe_synthetic_summaries_only",
        "excluded": [
            "sqlite authority files",
            "synthetic media",
            "spool and target object bytes",
            "virtual environments and caches",
            "private validation material",
        ],
        "files": records,
    }
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    (artifact / "manifest.json").write_bytes(manifest_bytes)
    checksum_records = [
        (path.name, _sha(path.read_bytes()))
        for path in sorted(artifact.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (artifact / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in checksum_records),
        encoding="utf-8",
    )
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path(".demo-output"))
    args = parser.parse_args(argv)
    try:
        artifact = package(args.output_root)
    except (ArtifactFailure, OSError) as exc:
        print(f"artifact packaging failed: {exc}", file=sys.stderr)
        return 2
    print(artifact.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
