"""Developer-experience contract for the deterministic local demo."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from demo.run_demo import run_demo
from scripts.inspect_demo import main as inspect_demo

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict[str, tuple[bool, int, str | None]]:
    result: dict[str, tuple[bool, int, str | None]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        result[relative] = (
            path.is_dir(),
            path.stat().st_mode,
            None if path.is_dir() else _sha(path),
        )
    return result


def test_demo_persists_complete_machine_and_human_evidence(tmp_path: Path) -> None:
    output = tmp_path / ".demo-output"
    receipt = run_demo(output)
    assert receipt["status"] == "pass"
    assert all(receipt["invariants"].values())
    for required in (
        "summary.json",
        "summary.txt",
        "manifest.json",
        "success/authority.sqlite3",
        "collision/authority.sqlite3",
    ):
        assert (output / required).is_file()
    assert "Replication worker deterministic local demo: PASS" in (
        output / "summary.txt"
    ).read_text(encoding="utf-8")
    machine = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert machine == receipt
    assert machine["success"]["target_lifecycle"]["initial_path"] == "created"
    assert machine["success"]["target_lifecycle"]["repeat_path"] == "adopted_existing"
    assert all(
        item["identity_and_content_match"]
        for item in machine["success"]["readback"]
    )


def test_demo_rerun_is_deterministic_and_safe(tmp_path: Path) -> None:
    output = tmp_path / ".demo-output"
    first = run_demo(output)
    first_summary = _sha(output / "summary.json")
    first_digest = json.loads(
        (output / "manifest.json").read_text(encoding="utf-8")
    )["deterministic_files_sha256"]
    second = run_demo(output)
    second_summary = _sha(output / "summary.json")
    second_digest = json.loads(
        (output / "manifest.json").read_text(encoding="utf-8")
    )["deterministic_files_sha256"]
    assert first == second
    assert first_summary == second_summary
    assert first_digest == second_digest
    assert second["success"]["rerun"]["authority_rows_unchanged"] is True


def test_demo_preserves_collision_and_verified_authority(tmp_path: Path) -> None:
    output = tmp_path / ".demo-output"
    receipt = run_demo(output)
    with sqlite3.connect(output / "success/authority.sqlite3") as connection:
        assert connection.execute(
            "SELECT count(*) FROM replica_objects WHERE state='VERIFIED'"
        ).fetchone() == (2,)
    with sqlite3.connect(output / "collision/authority.sqlite3") as connection:
        assert connection.execute(
            "SELECT state, last_error FROM replica_objects"
        ).fetchone() == ("PENDING", "destination_collision")
    collision = receipt["collision"]
    assert collision["wrong_bytes_preserved"] is True
    assert collision["expected_sha256"] != collision["observed_conflicting_sha256"]


def test_inspect_is_read_only(tmp_path: Path, capsys: object) -> None:
    output = tmp_path / ".demo-output"
    run_demo(output)
    before = _snapshot(output)
    assert inspect_demo(["--output-dir", str(output)]) == 0
    after = _snapshot(output)
    assert after == before
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Replication worker deterministic local demo: PASS" in captured.out


def test_developer_surface_is_present_and_demo_is_offline() -> None:
    for required in (
        ".devcontainer/devcontainer.json",
        ".devcontainer/Dockerfile",
        "scripts/setup.sh",
        "scripts/inspect_demo.py",
        "scripts/clean_demo.py",
        "Makefile",
    ):
        assert (ROOT / required).is_file()
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("demo:", "test:", "inspect:", "clean:"):
        assert target in makefile
    assert "rm -rf" not in makefile
    assert 'scripts/clean_demo.py --output-dir "$(DEMO_OUTPUT)"' in makefile
    demo = (ROOT / "demo/run_demo.py").read_text(encoding="utf-8").lower()
    for forbidden in (
        "requests",
        "urllib",
        "http.client",
        "socket",
        "boto",
        "google.cloud",
        "subprocess",
    ):
        assert forbidden not in demo
