from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "run_showcase.py"
ARTIFACT = ROOT / "scripts" / "package_ci_artifact.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_showcase = _load(DEMO, "run_showcase")
package_artifact = _load(ARTIFACT, "package_ci_artifact")


def _processor_summary(report_relative: str, report_sha: str) -> dict[str, object]:
    scenarios: dict[str, object] = {}
    for name in ("normal", "resume", "busy-lock"):
        scenarios[name] = {
            "status": "pass",
            "invariants": {"required": True},
        }
    scenarios["normal"]["verification"] = {
        "report_path": report_relative,
        "report_sha256": report_sha,
        "output_artifact_id": f"sha256:{report_sha}",
    }
    return {
        "schema_version": 1,
        "proof_class": "standalone_synthetic_processing_reliability",
        "status": "pass",
        "scenarios": scenarios,
    }


def test_processor_contract_binds_verified_report(tmp_path: Path) -> None:
    report = tmp_path / "normal" / "report.json"
    report.parent.mkdir()
    report.write_bytes(b'{"synthetic":true}\n')
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    result = run_showcase._validate_processor(
        _processor_summary("normal/report.json", digest), tmp_path
    )
    assert result["report"] == report
    assert result["report_sha256"] == digest
    assert result["output_artifact_id"] == f"sha256:{digest}"


def test_processor_contract_rejects_changed_report(tmp_path: Path) -> None:
    report = tmp_path / "normal" / "report.json"
    report.parent.mkdir()
    report.write_text("changed", encoding="utf-8")
    with pytest.raises(run_showcase.ShowcaseFailure):
        run_showcase._validate_processor(
            _processor_summary("normal/report.json", "0" * 64), tmp_path
        )


def test_replication_contract_requires_all_invariants() -> None:
    payload = {
        "schema_version": 2,
        "proof_class": "deterministic_local_replication",
        "status": "pass",
        "invariants": {"one": True, "two": True},
    }
    run_showcase._validate_replication(payload)
    payload["invariants"]["two"] = False
    with pytest.raises(run_showcase.ShowcaseFailure):
        run_showcase._validate_replication(payload)


def test_guarded_output_and_cleanup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_showcase, "ROOT", tmp_path)
    output = run_showcase._safe_output_root(Path(".demo-output-test"))
    output.mkdir()
    (output / "kept-only-until-clean").write_text("x", encoding="utf-8")
    sibling = tmp_path / "README.md"
    sibling.write_text("keep", encoding="utf-8")
    run_showcase.clean_demo(Path(".demo-output-test"))
    assert not output.exists()
    assert sibling.read_text(encoding="utf-8") == "keep"
    with pytest.raises(run_showcase.ShowcaseFailure):
        run_showcase._safe_output_root(Path("..") / ".demo-output")
    with pytest.raises(run_showcase.ShowcaseFailure):
        run_showcase._safe_output_root(Path("output"))


def test_child_environment_is_allowlisted(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-propagate")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/secret.json")
    environment = run_showcase._clean_environment()
    assert environment["PATH"] == "/bin"
    assert "GITHUB_TOKEN" not in environment
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in environment
    assert environment["PIP_NO_INDEX"] == "1"


def test_safe_ci_artifact_is_allowlisted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(package_artifact, "ROOT", tmp_path)
    output = tmp_path / ".demo-output"
    for relative in package_artifact.SAFE_PATHS:
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"status":"pass"}\n', encoding="utf-8")
    forbidden = output / "processor" / "authority.sqlite3"
    forbidden.write_bytes(b"sqlite")
    artifact = package_artifact.package(Path(".demo-output"))
    names = {path.name for path in artifact.iterdir()}
    assert "authority.sqlite3" not in names
    assert "manifest.json" in names
    assert "SHA256SUMS" in names
