"""Remove only guarded, disposable local replication-demo state."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

_OUTPUT_NAME = re.compile(r"^\.demo-output(?:-[a-z0-9][a-z0-9._-]*)?$")
_ROOT_DISPOSABLES = (".pytest_cache", "build", "dist")
_TREE_DISPOSABLE_NAMES = {"__pycache__"}
_TREE_DISPOSABLE_SUFFIXES = (".egg-info",)
_PRUNED_NAMES = {".git", ".venv"}
_PROTECTED_COMPONENTS = {".git"}


class CleanRefusal(ValueError):
    """Raised when a requested cleanup target is not provably safe."""


def _is_tree_disposable(name: str) -> bool:
    return name in _TREE_DISPOSABLE_NAMES or name.endswith(
        _TREE_DISPOSABLE_SUFFIXES
    )


def _reject_symlink_components(root: Path, target: Path) -> None:
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise CleanRefusal(f"symlink component is not removable: {part}")


def _validated_output(root: Path, raw_output: str) -> Path:
    value = raw_output.strip()
    if not value:
        raise CleanRefusal("demo output path is empty")
    if value in {"/", ".", ".."}:
        raise CleanRefusal("demo output path is a protected location")

    raw_path = Path(value)
    if ".." in raw_path.parts:
        raise CleanRefusal("parent traversal is forbidden")
    if any(part in _PROTECTED_COMPONENTS for part in raw_path.parts):
        raise CleanRefusal("protected repository metadata cannot be removed")
    if not _OUTPUT_NAME.fullmatch(raw_path.name):
        raise CleanRefusal("demo output directory must use a .demo-output name")

    lexical = raw_path if raw_path.is_absolute() else root / raw_path
    lexical = Path(os.path.abspath(lexical))
    try:
        lexical.relative_to(root)
    except ValueError as exc:
        raise CleanRefusal("demo output path is outside the repository") from exc

    resolved = lexical.resolve(strict=False)
    if resolved == root:
        raise CleanRefusal("repository root cannot be removed")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CleanRefusal("resolved demo output escapes the repository") from exc

    _reject_symlink_components(root, lexical)
    if lexical.exists() and not lexical.is_dir():
        raise CleanRefusal("demo output path is not a directory")
    return lexical


def _collect_disposable_directories(root: Path, output: Path) -> list[Path]:
    targets: set[Path] = {output}
    for name in _ROOT_DISPOSABLES:
        path = root / name
        if path.is_symlink():
            raise CleanRefusal(f"disposable path is a symlink: {name}")
        if path.exists() and not path.is_dir():
            raise CleanRefusal(f"disposable path is not a directory: {name}")
        targets.add(path)

    for current_text, dirnames, _filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_text)
        kept: list[str] = []
        for name in dirnames:
            path = current / name
            relative = path.relative_to(root)
            if path.is_symlink():
                if _is_tree_disposable(name):
                    raise CleanRefusal(
                        f"disposable path is a symlink: {relative.as_posix()}"
                    )
                continue
            if name in _PRUNED_NAMES or path == output:
                continue
            if _is_tree_disposable(name):
                targets.add(path)
                continue
            kept.append(name)
        dirnames[:] = kept

    return sorted(targets, key=lambda path: (len(path.parts), path.as_posix()), reverse=True)


def clean_repository(repository_root: Path, output_dir: str) -> list[str]:
    root = repository_root.resolve(strict=True)
    if not root.is_dir() or repository_root.is_symlink():
        raise CleanRefusal("repository root must be a real directory")

    output = _validated_output(root, output_dir)
    targets = _collect_disposable_directories(root, output)
    removed: list[str] = []
    for target in targets:
        if not target.exists():
            continue
        _reject_symlink_components(root, target)
        if target.is_symlink() or not target.is_dir():
            raise CleanRefusal(
                f"cleanup target changed type: {target.relative_to(root).as_posix()}"
            )
        shutil.rmtree(target)
        removed.append(target.relative_to(root).as_posix())
    return sorted(removed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    repository_root = Path(__file__).resolve().parents[1]
    try:
        removed = clean_repository(repository_root, args.output_dir)
    except (CleanRefusal, OSError) as exc:
        print(f"clean refused: {exc}", file=sys.stderr)
        return 2
    if removed:
        print("Removed disposable local directories:")
        for path in removed:
            print(f"  {path}")
    else:
        print("No disposable local directories were present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
