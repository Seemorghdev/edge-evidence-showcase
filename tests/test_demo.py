from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

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


def _inspection_fixture(tmp_path: Path) -> tuple[Path, Path]:
    output = tmp_path / ".demo-output-test"
    report = output / "processor" / "normal" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_bytes(b'{"synthetic":true}\n')

    handoff_summary = output / "handoff" / "summary.txt"
    handoff_summary.parent.mkdir(parents=True)
    handoff_summary.write_text("handoff pass\n", encoding="utf-8")

    combined = output / "combined"
    combined.mkdir(parents=True)
    run_showcase._write_json(
        combined / "summary.json",
        {
            "schema_version": 1,
            "status": "pass",
            "components": {
                "processor": {
                    "output_path": "processor/normal/report.json",
                    "output_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
                }
            },
        },
    )
    (combined / "summary.txt").write_text("combined pass\n", encoding="utf-8")
    run_showcase._write_json(combined / "manifest.json", run_showcase._output_manifest(output))
    return output, report


def _stub_component_inspect(monkeypatch) -> None:
    monkeypatch.setattr(
        run_showcase,
        "_require_executable",
        lambda path, label: str(path),
    )
    monkeypatch.setattr(
        run_showcase,
        "_run_component_make",
        lambda *args, **kwargs: SimpleNamespace(stdout=""),
    )


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


def test_inspect_clean_evidence_is_read_only(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(run_showcase, "ROOT", tmp_path)
    _inspection_fixture(tmp_path)
    _stub_component_inspect(monkeypatch)

    before = run_showcase.deterministic_fingerprint(Path(".demo-output-test"))
    run_showcase.inspect_demo(
        Path(".demo-output-test"), Path("processor-python"), Path("replication-python")
    )
    after = run_showcase.deterministic_fingerprint(Path(".demo-output-test"))

    assert before == after
    assert "Combined machine summary" in capsys.readouterr().out


def test_inspect_missing_demo_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_showcase, "ROOT", tmp_path)
    with pytest.raises(run_showcase.ShowcaseFailure, match="demo output is missing"):
        run_showcase.inspect_demo(
            Path(".demo-output-test"),
            Path("processor-python"),
            Path("replication-python"),
        )


def test_inspect_rejects_retained_deterministic_artifact_tamper(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(run_showcase, "ROOT", tmp_path)
    _, report = _inspection_fixture(tmp_path)
    _stub_component_inspect(monkeypatch)

    before = run_showcase.deterministic_fingerprint(Path(".demo-output-test"))
    with report.open("ab") as handle:
        handle.write(b"\nTAMPER\n")
    after = run_showcase.deterministic_fingerprint(Path(".demo-output-test"))

    assert before != after
    with pytest.raises(
        run_showcase.ShowcaseFailure,
        match=(
            "retained deterministic artifact integrity mismatch: "
            "processor/normal/report.json"
        ),
    ):
        run_showcase.inspect_demo(
            Path(".demo-output-test"),
            Path("processor-python"),
            Path("replication-python"),
        )
    assert capsys.readouterr().out == ""


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
