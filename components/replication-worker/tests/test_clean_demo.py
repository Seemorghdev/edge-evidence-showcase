from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.clean_demo import CleanRefusal, clean_repository


def _directory(path: Path, filename: str = "marker.txt") -> Path:
    path.mkdir(parents=True)
    (path / filename).write_text("disposable\n", encoding="utf-8")
    return path


def test_safe_cleanup_removes_only_selected_and_named_disposables(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    selected = _directory(root / "artifacts/.demo-output-test")
    disposables = {
        _directory(root / ".pytest_cache"),
        _directory(root / "build"),
        _directory(root / "dist"),
        _directory(root / "packages/example/__pycache__"),
        _directory(root / "edge_evidence_replication_worker.egg-info"),
    }
    retained = root / "packages/example/source.py"
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_text("retained = True\n", encoding="utf-8")
    git_marker = _directory(root / ".git", "HEAD")
    venv_marker = _directory(root / ".venv", "pyvenv.cfg")

    removed = clean_repository(root, "artifacts/.demo-output-test")

    assert not selected.exists()
    assert all(not path.exists() for path in disposables)
    assert retained.read_text(encoding="utf-8") == "retained = True\n"
    assert git_marker.is_dir()
    assert venv_marker.is_dir()
    assert "artifacts/.demo-output-test" in removed


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "/",
        ".",
        "..",
        "../escape",
        "nested/../../escape",
        ".git/.demo-output",
        "packages",
    ],
)
def test_cleanup_refuses_unsafe_output_values(tmp_path: Path, value: str) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    with pytest.raises(CleanRefusal):
        clean_repository(root, value)


def test_cleanup_refuses_repository_root_and_outside_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    outside = tmp_path / ".demo-output-outside"
    outside.mkdir()
    for value in (str(root), str(outside)):
        with pytest.raises(CleanRefusal):
            clean_repository(root, value)
    assert outside.is_dir()


def test_cleanup_refuses_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    outside = _directory(tmp_path / "outside/.demo-output")
    link = root / "linked"
    try:
        os.symlink(outside.parent, link, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")

    with pytest.raises(CleanRefusal):
        clean_repository(root, "linked/.demo-output")
    assert outside.is_dir()


def test_cleanup_refuses_symlinked_selected_directory(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    outside = _directory(tmp_path / ".demo-output-external")
    selected = root / ".demo-output"
    try:
        os.symlink(outside, selected, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")

    with pytest.raises(CleanRefusal):
        clean_repository(root, ".demo-output")
    assert outside.is_dir()
