#!/usr/bin/env python3
"""Verify the generated worker bundle before local installation or execution."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "BUNDLE_MANIFEST.json"
IGNORED = {".git", ".venv", ".pytest_cache", "build", "dist", "__pycache__"}


class BundleError(RuntimeError):
    """The generated component bundle is incomplete or has drifted."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _candidate_files(root: Path) -> dict[str, tuple[str, bytes]]:
    result: dict[str, tuple[str, bytes]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED or part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        mode = "100755" if stat.S_IMODE(path.stat().st_mode) & 0o111 else "100644"
        result[relative.as_posix()] = (mode, path.read_bytes())
    return result


def _tree_digest(files: dict[str, tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        mode, data = files[path]
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(_sha(data).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def verify() -> dict[str, object]:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"invalid bundle manifest: {exc}") from exc
    if manifest.get("schema") != "edge-evidence-showcase-bundle.v1":
        raise BundleError("bundle manifest schema mismatch")
    components = manifest.get("components")
    if not isinstance(components, dict) or set(components) != {
        "processor-worker",
        "replication-worker",
    }:
        raise BundleError("bundle manifest must bind exactly both generated workers")

    checked: dict[str, object] = {}
    for component in sorted(components):
        record = components[component]
        if not isinstance(record, dict):
            raise BundleError(f"invalid component record: {component}")
        expected_path = f"components/{component}"
        if record.get("path") != expected_path:
            raise BundleError(f"component path mismatch: {component}")
        root = ROOT / expected_path
        if not root.is_dir() or root.is_symlink():
            raise BundleError(f"generated component is absent or unsafe: {component}")
        files = _candidate_files(root)
        provenance_path = "EXPORT_PROVENANCE.json"
        if provenance_path not in files:
            raise BundleError(f"component provenance is absent: {component}")
        provenance = json.loads(files[provenance_path][1].decode("utf-8"))
        if provenance.get("component") != component:
            raise BundleError(f"component provenance identity mismatch: {component}")
        without_provenance = {
            path: value for path, value in files.items() if path != provenance_path
        }
        digest = _tree_digest(without_provenance)
        if digest != provenance.get("candidate_content_tree_sha256"):
            raise BundleError(f"component content digest mismatch: {component}")
        if digest != record.get("candidate_content_tree_sha256"):
            raise BundleError(f"bundle manifest digest mismatch: {component}")
        if len(files) != provenance.get("candidate_path_count"):
            raise BundleError(f"component path count mismatch: {component}")
        if len(files) != record.get("candidate_path_count"):
            raise BundleError(f"bundle manifest path count mismatch: {component}")
        checked[component] = {
            "path_count": len(files),
            "candidate_content_tree_sha256": digest,
        }
    return {
        "schema": "edge-evidence-showcase-bundle-verification.v1",
        "status": "pass",
        "components": checked,
    }


def main() -> int:
    try:
        result = verify()
    except (BundleError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"bundle verification failed: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
