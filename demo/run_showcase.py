#!/usr/bin/env python3
"""Run, inspect, fingerprint, or clean the integrated synthetic showcase."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / ".demo-output"
_OUTPUT_NAME = re.compile(r"^\.demo-output(?:-[a-z0-9][a-z0-9._-]*)?$")
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP")


class ShowcaseFailure(RuntimeError):
    """The integrated showcase failed closed."""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical(payload) + "\n", encoding="utf-8")


def _safe_output_root(raw: Path) -> Path:
    if raw.is_symlink():
        raise ShowcaseFailure("demo output cannot be a symlink")
    if ".." in raw.parts or ".git" in raw.parts:
        raise ShowcaseFailure("demo output contains a protected path component")
    lexical = raw if raw.is_absolute() else ROOT / raw
    lexical = Path(os.path.abspath(lexical))
    if not _OUTPUT_NAME.fullmatch(lexical.name):
        raise ShowcaseFailure("demo output must use a .demo-output name")
    try:
        lexical.relative_to(ROOT)
    except ValueError as exc:
        raise ShowcaseFailure("demo output must remain inside the showcase repository") from exc
    resolved = lexical.resolve(strict=False)
    if resolved in {ROOT, ROOT.parent, Path(resolved.anchor)}:
        raise ShowcaseFailure("refusing protected demo output location")
    try:
        resolved.relative_to(ROOT)
    except ValueError as exc:
        raise ShowcaseFailure("resolved demo output escapes the showcase repository") from exc
    current = ROOT
    for part in lexical.relative_to(ROOT).parts:
        current = current / part
        if current.is_symlink():
            raise ShowcaseFailure(f"symlink component is forbidden: {part}")
    return lexical


def _clean_environment() -> dict[str, str]:
    env = {
        name: value
        for name in _ENV_ALLOWLIST
        if (value := os.environ.get(name)) is not None
    }
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PIP_NO_INDEX": "1",
            "NO_PROXY": "*",
            "no_proxy": "*",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
        }
    )
    return env


def _require_executable(path: Path, label: str) -> str:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ShowcaseFailure(f"{label} environment is missing; run './scripts/setup.sh'")
    return str(resolved)


def _run(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=_clean_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise ShowcaseFailure(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _run_component_make(
    component: str,
    target: str,
    python: str,
    output: Path,
) -> subprocess.CompletedProcess[str]:
    make = shutil.which("make")
    if make is None:
        raise ShowcaseFailure("required local tool not found: make")
    component_root = ROOT / "components" / component
    if component == "processor-worker":
        variable = f"OUTPUT_ROOT={output}"
    elif component == "replication-worker":
        variable = f"DEMO_OUTPUT={output}"
    else:  # pragma: no cover - internal contract
        raise ShowcaseFailure(f"unknown component: {component}")
    return _run(
        [
            make,
            "-C",
            str(component_root),
            f"PYTHON={python}",
            variable,
            target,
        ]
    )


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShowcaseFailure(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ShowcaseFailure(f"{label} must be a JSON object")
    return payload


def _validate_processor(summary: dict[str, Any], output: Path) -> dict[str, Any]:
    if (
        summary.get("schema_version") != 1
        or summary.get("proof_class")
        != "standalone_synthetic_processing_reliability"
        or summary.get("status") != "pass"
    ):
        raise ShowcaseFailure("processor summary contract mismatch")
    scenarios = summary.get("scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != {
        "normal",
        "resume",
        "busy-lock",
    }:
        raise ShowcaseFailure("processor scenarios are incomplete")
    for name, receipt in scenarios.items():
        if not isinstance(receipt, dict) or receipt.get("status") != "pass":
            raise ShowcaseFailure(f"processor scenario failed: {name}")
        invariants = receipt.get("invariants")
        if not isinstance(invariants, dict) or not all(invariants.values()):
            raise ShowcaseFailure(f"processor scenario invariant failed: {name}")
    normal = scenarios["normal"]
    verification = normal.get("verification")
    if not isinstance(verification, dict):
        raise ShowcaseFailure("processor normal verification is absent")
    report_relative = verification.get("report_path")
    report_sha = verification.get("report_sha256")
    if not isinstance(report_relative, str) or not isinstance(report_sha, str):
        raise ShowcaseFailure("processor report identity is absent")
    report = output / report_relative
    if not report.is_file() or _sha(report) != report_sha:
        raise ShowcaseFailure("processor report bytes do not match the verified receipt")
    return {
        "report": report,
        "report_relative": report_relative,
        "report_sha256": report_sha,
        "output_artifact_id": verification.get("output_artifact_id"),
    }


def _validate_replication(summary: dict[str, Any]) -> None:
    if (
        summary.get("schema_version") != 2
        or summary.get("proof_class") != "deterministic_local_replication"
        or summary.get("status") != "pass"
    ):
        raise ShowcaseFailure("replication summary contract mismatch")
    invariants = summary.get("invariants")
    if not isinstance(invariants, dict) or not all(invariants.values()):
        raise ShowcaseFailure("replication invariant failure")


def _run_handoff(
    replication_python: str,
    source: Path,
    source_label: str,
    output: Path,
) -> dict[str, Any]:
    completed = _run(
        [
            replication_python,
            str(ROOT / "scripts" / "run_replication_handoff.py"),
            "--source",
            str(source),
            "--source-label",
            source_label,
            "--output-dir",
            str(output),
        ]
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ShowcaseFailure("handoff subprocess did not emit exactly one JSON object")
    payload = json.loads(lines[0])
    if not isinstance(payload, dict) or payload.get("status") != "pass":
        raise ShowcaseFailure("handoff subprocess failed")
    invariants = payload.get("invariants")
    if not isinstance(invariants, dict) or not all(invariants.values()):
        raise ShowcaseFailure("handoff invariant failure")
    return payload


def _render(summary: dict[str, Any]) -> str:
    processor = summary["components"]["processor"]
    handoff = summary["handoff"]
    lines = [
        "Edge Evidence integrated synthetic showcase: PASS",
        "",
        (
            "Processor: normal + committed resume + busy-lock defer/retry; "
            f"report={processor['output_artifact_id']}"
        ),
        (
            "Replication: target lifecycle + exact adoption + immutable create + "
            "readback + collision refusal"
        ),
        (
            "End-to-end: processor report replicated with SHA-256 "
            f"{handoff['source']['sha256']}"
        ),
        f"Target: {handoff['replication']['target_path']}",
        "Replay: no new processing or replication writes",
        "Isolation: separate processor and replication Python environments",
        "Network/credentials/models/publication: none",
        "",
        "Inspect with: make inspect",
        "Clean with: make clean",
        "Combined summary: .demo-output/combined/summary.json",
        "Scope: synthetic local demonstration only; not persistent evidence authority",
        "",
    ]
    return "\n".join(lines)


def _output_manifest(root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == root / "combined" / "manifest.json":
            continue
        relative = path.relative_to(root).as_posix()
        if path.name == ".edge-agent.lock" or path.suffix in {".sqlite3", ".mp4"}:
            files.append(
                {
                    "path": relative,
                    "kind": "inspectable_local_state",
                    "byte_size": path.stat().st_size,
                }
            )
        else:
            files.append(
                {
                    "path": relative,
                    "kind": "deterministic_file",
                    "byte_size": path.stat().st_size,
                    "sha256": _sha(path),
                }
            )
    return {
        "schema_version": 1,
        "status": "pass",
        "files": files,
    }


def run_demo(
    output_root: Path,
    processor_python: Path,
    replication_python: Path,
) -> dict[str, Any]:
    output_root = _safe_output_root(output_root)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    processor_python_text = _require_executable(processor_python, "processor")
    replication_python_text = _require_executable(replication_python, "replication")
    processor_output = output_root / "processor"
    replication_output = output_root / "replication"
    handoff_output = output_root / "handoff"

    _run_component_make(
        "processor-worker", "demo", processor_python_text, processor_output
    )
    processor_summary_path = processor_output / "summary.json"
    processor_summary = _load_object(processor_summary_path, "processor summary")
    processor_result = _validate_processor(processor_summary, processor_output)

    _run_component_make(
        "replication-worker", "demo", replication_python_text, replication_output
    )
    replication_summary_path = replication_output / "summary.json"
    replication_summary = _load_object(replication_summary_path, "replication summary")
    _validate_replication(replication_summary)

    source_label = f"processor/{processor_result['report_relative']}"
    handoff = _run_handoff(
        replication_python_text,
        processor_result["report"],
        source_label,
        handoff_output,
    )
    if handoff["source"]["sha256"] != processor_result["report_sha256"]:
        raise ShowcaseFailure("handoff source digest differs from processor verification")
    if handoff["source"]["processor_output_artifact_id"] != processor_result[
        "output_artifact_id"
    ]:
        raise ShowcaseFailure("handoff source identity differs from processor output")

    summary: dict[str, Any] = {
        "schema_version": 1,
        "proof_class": "integrated_synthetic_processing_and_replication",
        "status": "pass",
        "constraints": {
            "synthetic_inputs_only": True,
            "network_required": False,
            "credentials_required": False,
            "external_service_required": False,
            "model_required": False,
            "adk_executed": False,
            "ollama_executed": False,
            "publication_performed": False,
            "persistent_evidence_authority_claimed": False,
        },
        "composition": {
            "separate_python_environments": True,
            "shared_worker_import_process": False,
            "generated_processor_package": "components/processor-worker",
            "generated_replication_package": "components/replication-worker",
            "orchestration_channels": [
                "subprocess_exit_status",
                "json_receipts",
                "filesystem_paths",
                "sha256",
            ],
        },
        "components": {
            "processor": {
                "status": processor_summary["status"],
                "proof_class": processor_summary["proof_class"],
                "summary_path": "processor/summary.json",
                "summary_sha256": _sha(processor_summary_path),
                "output_artifact_id": processor_result["output_artifact_id"],
                "output_path": source_label,
                "output_sha256": processor_result["report_sha256"],
            },
            "replication": {
                "status": replication_summary["status"],
                "proof_class": replication_summary["proof_class"],
                "summary_path": "replication/summary.json",
                "summary_sha256": _sha(replication_summary_path),
            },
        },
        "handoff": handoff,
        "invariants": {
            "processor_reliability_proofs_passed": True,
            "replication_standalone_proofs_passed": True,
            "processor_output_replicated_by_identity": True,
            "replicated_bytes_match_processor_output": True,
            "integrated_replication_replay_is_noop": True,
            "zero_unresolved_integrated_work": True,
            "worker_authority_boundaries_preserved": True,
        },
        "artifacts": {
            "human_summary": "combined/summary.txt",
            "machine_summary": "combined/summary.json",
            "manifest": "combined/manifest.json",
        },
        "limitations": [
            "Synthetic local demonstration only.",
            "No production, availability, performance, fleet, or persistence claim.",
            "The local mounted-filesystem contract is not physical NAS or cloud proof.",
            "Container-local files are demonstration state, not persistent evidence authority.",
        ],
    }
    fingerprint_payload = dict(summary)
    summary["run_fingerprint"] = f"sha256:{hashlib.sha256(_canonical(fingerprint_payload).encode()).hexdigest()}"

    combined = output_root / "combined"
    combined.mkdir()
    _write_json(combined / "summary.json", summary)
    human = _render(summary)
    (combined / "summary.txt").write_text(human, encoding="utf-8")
    _write_json(combined / "manifest.json", _output_manifest(output_root))
    print(human, end="")
    print(_canonical(summary))
    return summary


def deterministic_fingerprint(output_root: Path) -> dict[str, str]:
    root = _safe_output_root(output_root)
    if not (root / "combined" / "summary.json").is_file():
        raise ShowcaseFailure("demo output is missing; run 'make demo' first")
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == ".edge-agent.lock" or path.suffix in {".sqlite3", ".mp4"}:
            continue
        result[path.relative_to(root).as_posix()] = _sha(path)
    return result


def inspect_demo(
    output_root: Path,
    processor_python: Path,
    replication_python: Path,
) -> None:
    root = _safe_output_root(output_root)
    combined = root / "combined" / "summary.json"
    if not combined.is_file():
        raise ShowcaseFailure("demo output is missing; run 'make demo' first")
    processor_python_text = _require_executable(processor_python, "processor")
    replication_python_text = _require_executable(replication_python, "replication")
    processor = _run_component_make(
        "processor-worker", "inspect", processor_python_text, root / "processor"
    )
    replication = _run_component_make(
        "replication-worker", "inspect", replication_python_text, root / "replication"
    )
    print(processor.stdout, end="")
    print(replication.stdout, end="")
    print((root / "handoff" / "summary.txt").read_text(encoding="utf-8"), end="")
    print((root / "combined" / "summary.txt").read_text(encoding="utf-8"), end="")
    print("Combined machine summary")
    print("------------------------")
    print(json.dumps(_load_object(combined, "combined summary"), indent=2, sort_keys=True))


def clean_demo(output_root: Path) -> None:
    root = _safe_output_root(output_root)
    if root.exists():
        shutil.rmtree(root)
        print(f"removed {root.relative_to(ROOT).as_posix()}")
    else:
        print("no showcase demo output was present")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--processor-python",
        type=Path,
        default=ROOT / ".venv" / "processor" / "bin" / "python",
    )
    parser.add_argument(
        "--replication-python",
        type=Path,
        default=ROOT / ".venv" / "replication" / "bin" / "python",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("demo")
    subparsers.add_parser("inspect")
    subparsers.add_parser("fingerprint")
    subparsers.add_parser("clean")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "demo"
    try:
        if command == "demo":
            run_demo(args.output_root, args.processor_python, args.replication_python)
        elif command == "inspect":
            inspect_demo(args.output_root, args.processor_python, args.replication_python)
        elif command == "fingerprint":
            print(_canonical(deterministic_fingerprint(args.output_root)))
        elif command == "clean":
            clean_demo(args.output_root)
        else:  # pragma: no cover
            raise ShowcaseFailure(f"unknown command: {command}")
    except (ShowcaseFailure, OSError, json.JSONDecodeError) as exc:
        print(f"showcase error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
