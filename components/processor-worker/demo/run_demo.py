"""Persistent synthetic reliability demonstration for the exported processor worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from apps.edge_agent import finalize
from packages.database.migrations import migrate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / ".demo-output"
STARTED_AT = "2026-08-11T10:00:00Z"
FINALIZED_AT = "2026-08-11T10:00:10Z"
INTERRUPTED_EXIT = 86
SCENARIOS = ("normal", "resume", "busy-lock")


class DemoFailure(RuntimeError):
    """A deterministic demonstration assertion failed."""


def _require_tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise DemoFailure(f"required tool not found: {name}")
    return executable


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, output_root: Path) -> str:
    return path.relative_to(output_root).as_posix()


def _generate_media(path: Path) -> None:
    ffmpeg = _require_tool("ffmpeg")
    _require_tool("ffprobe")
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=15:duration=10",
            "-frames:v",
            "150",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "15",
            "-keyint_min",
            "15",
            "-sc_threshold",
            "0",
            "-threads",
            "1",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            "-an",
            "-y",
            str(path),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise DemoFailure(f"ffmpeg failed: {completed.stderr.strip()}")


def _seed(database: Path, spool: Path, media: Path, label: str) -> str:
    media_bytes = media.read_bytes()
    digest = hashlib.sha256(media_bytes).hexdigest()
    artifact_id = f"sha256:{digest}"
    source_id = f"synthetic-{label}"
    occurrence_id = f"occ-{label}"
    session_id = f"sess-{label}"

    final_media = spool / finalize.media_relative_path(digest)
    final_manifest = spool / finalize.manifest_relative_path(digest)
    final_media.parent.mkdir(parents=True, exist_ok=True)
    final_manifest.parent.mkdir(parents=True, exist_ok=True)
    final_media.write_bytes(media_bytes)
    manifest = {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "source_id": source_id,
        "artifact_kind": "raw_media",
        "media_type": "video/mp4",
        "byte_size": len(media_bytes),
        "digest": {"algorithm": "sha256", "value": digest},
        "storage_uri": finalize.storage_uri(digest),
        "finalized_at": FINALIZED_AT,
    }
    manifest_bytes = finalize.serialize_manifest(manifest)
    final_manifest.write_bytes(manifest_bytes)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_uri = f"file:manifests/sha256/{digest[:2]}/{digest}.json"

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO artifacts (artifact_id, source_id, artifact_kind, media_type, "
            "byte_size, digest_algorithm, digest_value, storage_uri, manifest_uri, "
            "manifest_sha256, finalized_at) VALUES (?, ?, 'raw_media', 'video/mp4', ?, "
            "'sha256', ?, ?, ?, ?, ?)",
            (
                artifact_id,
                source_id,
                len(media_bytes),
                digest,
                finalize.storage_uri(digest),
                manifest_uri,
                manifest_sha,
                FINALIZED_AT,
            ),
        )
        connection.execute(
            "INSERT INTO expected_occurrences (occurrence_id, source_id, session_id, "
            "sequence_number, expected_started_at, expected_ended_at, state, artifact_id, "
            "terminal_at) VALUES (?, ?, ?, 1, ?, ?, 'COMPLETE', ?, ?)",
            (
                occurrence_id,
                source_id,
                session_id,
                STARTED_AT,
                FINALIZED_AT,
                artifact_id,
                FINALIZED_AT,
            ),
        )
        connection.execute(
            "INSERT INTO capture_occurrences (occurrence_id, source_id, session_id, "
            "sequence_number, capture_started_at, capture_ended_at, artifact_id) "
            "VALUES (?, ?, ?, 1, ?, ?, ?)",
            (
                occurrence_id,
                source_id,
                session_id,
                STARTED_AT,
                FINALIZED_AT,
                artifact_id,
            ),
        )
        connection.execute(
            "INSERT INTO capture_occurrence_assertions (occurrence_id, source_id, "
            "artifact_id, manifest_layout, manifest_uri, manifest_sha256, finalized_at) "
            "VALUES (?, ?, ?, 'legacy_digest_v1', ?, ?, ?)",
            (
                occurrence_id,
                source_id,
                artifact_id,
                manifest_uri,
                manifest_sha,
                FINALIZED_AT,
            ),
        )
        connection.commit()
    return artifact_id


def _prepare_case(output_root: Path, name: str, fixture_media: Path) -> tuple[Path, Path, Path, str]:
    case_root = output_root / name
    case_root.mkdir(parents=True, exist_ok=False)
    database = case_root / "authority.sqlite3"
    spool = case_root / "spool"
    input_media = case_root / "input" / "synthetic.mp4"
    spool.mkdir()
    input_media.parent.mkdir()
    shutil.copyfile(fixture_media, input_media)
    migration = migrate(database)
    if migration.current_version != 10:
        raise DemoFailure("fresh authority database did not reach schema version 10")
    artifact_id = _seed(database, spool, input_media, name.replace("-", "_"))
    return database, spool, input_media, artifact_id


def _run_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _invoke_worker(database: Path, spool: Path) -> dict[str, Any]:
    completed = _run_command(
        [
            sys.executable,
            "-m",
            "apps.processor_worker.cli",
            "run",
            "--database",
            str(database),
            "--spool-root",
            str(spool),
        ]
    )
    if completed.returncode != 0:
        raise DemoFailure(
            "processor-worker failed with exit "
            f"{completed.returncode}: {completed.stderr.strip()}"
        )
    if completed.stderr.strip():
        raise DemoFailure(f"processor-worker emitted stderr: {completed.stderr.strip()}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise DemoFailure("processor-worker did not emit exactly one JSON summary")
    payload = json.loads(lines[0])
    if not isinstance(payload, dict):
        raise DemoFailure("processor-worker summary was not a JSON object")
    return payload


def _expect_summary(summary: dict[str, Any], **expected: Any) -> None:
    baseline = {
        "status": "pass",
        "snapshot_eligible": 1,
        "already_complete": 0,
        "prepared_resumed": 0,
        "newly_completed": 0,
        "deferred": 0,
        "remaining": 0,
    }
    baseline.update(expected)
    if summary != baseline:
        raise DemoFailure(f"unexpected processor-worker summary: {summary}")


def _file_uri_path(spool: Path, uri: str) -> Path:
    if not uri.startswith("file:"):
        raise DemoFailure("derived URI was not a relative file URI")
    relative = Path(uri[5:])
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise DemoFailure("derived URI was not canonical and relative")
    return spool.joinpath(*relative.parts)


def _authority_state(database: Path) -> dict[str, Any]:
    with sqlite3.connect(database) as connection:
        job_rows = connection.execute(
            "SELECT job_id, state, input_artifact_id, output_artifact_id "
            "FROM processing_jobs ORDER BY job_id"
        ).fetchall()
        artifact_counts = dict(
            connection.execute(
                "SELECT artifact_kind, COUNT(*) FROM artifacts GROUP BY artifact_kind"
            ).fetchall()
        )
        lineage_count = int(
            connection.execute("SELECT COUNT(*) FROM artifact_lineage").fetchone()[0]
        )
    return {
        "jobs": [
            {
                "job_id": str(row[0]),
                "state": str(row[1]),
                "input_artifact_id": str(row[2]),
                "output_artifact_id": None if row[3] is None else str(row[3]),
            }
            for row in job_rows
        ],
        "raw_artifacts": int(artifact_counts.get("raw_media", 0)),
        "metadata_artifacts": int(artifact_counts.get("metadata", 0)),
        "lineage_rows": lineage_count,
    }


def _verify_completion(
    database: Path,
    spool: Path,
    input_artifact_id: str,
    output_root: Path,
) -> dict[str, Any]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT j.job_id, j.state, j.input_artifact_id, j.output_artifact_id, "
            "j.processor_name, j.processor_version, j.output_contract, "
            "l.parent_artifact_id, l.relation_type, a.artifact_kind, a.media_type, "
            "a.storage_uri, a.manifest_uri, a.digest_value, a.manifest_sha256 "
            "FROM processing_jobs AS j "
            "JOIN artifact_lineage AS l ON l.child_artifact_id = j.output_artifact_id "
            "JOIN artifacts AS a ON a.artifact_id = j.output_artifact_id"
        ).fetchall()
    if len(rows) != 1:
        raise DemoFailure("expected exactly one complete processing job and lineage row")

    (
        job_id,
        state,
        recorded_input,
        output_artifact_id,
        processor_name,
        processor_version,
        output_contract,
        lineage_parent,
        relation_type,
        artifact_kind,
        media_type,
        storage_uri,
        manifest_uri,
        digest_value,
        manifest_sha256,
    ) = rows[0]
    report_path = _file_uri_path(spool, str(storage_uri))
    manifest_path = _file_uri_path(spool, str(manifest_uri))
    report_bytes = report_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    report = json.loads(report_bytes.decode("utf-8"))

    checks = {
        "job_complete": state == "COMPLETE",
        "input_bound": recorded_input == input_artifact_id,
        "output_identity_verified": (
            output_artifact_id == f"sha256:{digest_value}"
            and hashlib.sha256(report_bytes).hexdigest() == digest_value
        ),
        "manifest_sha256_verified": (
            hashlib.sha256(manifest_bytes).hexdigest() == manifest_sha256
        ),
        "lineage_verified": (
            lineage_parent == input_artifact_id and relation_type == "derived_from"
        ),
        "contract_verified": (
            processor_name == "artifact-fingerprint"
            and processor_version == "1"
            and output_contract == "artifact-fingerprint-report.v1"
            and artifact_kind == "metadata"
            and media_type
            == "application/vnd.seemorgh.artifact-fingerprint-report.v1+json"
            and report.get("report_kind") == "artifact-fingerprint-report.v1"
            and report.get("input", {}).get("artifact_id") == input_artifact_id
        ),
    }
    if not all(checks.values()):
        raise DemoFailure(f"derived output verification failed: {checks}")
    return {
        "job_id": str(job_id),
        "output_artifact_id": str(output_artifact_id),
        "report_path": _relative(report_path, output_root),
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "manifest_path": _relative(manifest_path, output_root),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "checks": checks,
    }


def _scenario_summary_text(name: str, receipt: dict[str, Any]) -> str:
    lines = [
        f"Scenario: {name}",
        f"Status: {receipt['status']}",
        f"Input artifact: {receipt['input']['artifact_id']}",
    ]
    for label, summary in receipt["worker_runs"].items():
        lines.append(
            f"{label}: status={summary['status']} "
            f"new={summary['newly_completed']} resumed={summary['prepared_resumed']} "
            f"existing={summary['already_complete']} deferred={summary['deferred']} "
            f"remaining={summary['remaining']}"
        )
    final = receipt["final_authority"]
    lines.extend(
        [
            f"Final jobs: {len(final['jobs'])}",
            f"Final metadata artifacts: {final['metadata_artifacts']}",
            f"Final lineage rows: {final['lineage_rows']}",
            f"Receipt: {name}/receipt.json",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_scenario(output_root: Path, name: str, receipt: dict[str, Any]) -> None:
    case_root = output_root / name
    _write_json(case_root / "receipt.json", receipt)
    (case_root / "summary.txt").write_text(
        _scenario_summary_text(name, receipt), encoding="utf-8"
    )


def _run_normal(output_root: Path, fixture_media: Path) -> dict[str, Any]:
    database, spool, input_media, artifact_id = _prepare_case(
        output_root, "normal", fixture_media
    )
    before = _authority_state(database)
    first = _invoke_worker(database, spool)
    _expect_summary(first, newly_completed=1)
    verification = _verify_completion(database, spool, artifact_id, output_root)
    after_first = _authority_state(database)
    replay = _invoke_worker(database, spool)
    _expect_summary(replay, already_complete=1)
    after_replay = _authority_state(database)
    if after_replay != after_first:
        raise DemoFailure("normal replay changed authoritative database state")
    receipt = {
        "schema_version": 1,
        "scenario": "normal",
        "proof_class": "standalone_synthetic_processing_normal",
        "status": "pass",
        "input": {
            "artifact_id": artifact_id,
            "media_path": _relative(input_media, output_root),
            "media_sha256": _sha256(input_media),
        },
        "before": before,
        "worker_runs": {"first": first, "replay": replay},
        "verification": verification,
        "final_authority": after_replay,
        "invariants": {
            "real_worker_invoked": True,
            "derived_files_verified": True,
            "lineage_verified": True,
            "replay_idempotent": True,
        },
    }
    _write_scenario(output_root, "normal", receipt)
    return receipt


def _interrupt_child(database: Path, spool: Path, artifact_id: str) -> int:
    from apps.edge_agent import process

    def stop_after_prepared() -> None:
        os._exit(INTERRUPTED_EXIT)

    process.set_barrier("after_prepared_commit", stop_after_prepared)
    process.process_artifact(
        process.ProcessRequest(
            database_path=str(database),
            spool_root=str(spool),
            input_artifact_id=artifact_id,
            profile="integrity",
        )
    )
    return 0


def _run_resume(output_root: Path, fixture_media: Path) -> dict[str, Any]:
    database, spool, input_media, artifact_id = _prepare_case(
        output_root, "resume", fixture_media
    )
    interrupted = _run_command(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "_interrupt-child",
            "--database",
            str(database),
            "--spool-root",
            str(spool),
            "--artifact-id",
            artifact_id,
        ]
    )
    if interrupted.returncode != INTERRUPTED_EXIT:
        raise DemoFailure(
            "interruption child did not stop at the committed checkpoint: "
            f"exit={interrupted.returncode} stderr={interrupted.stderr.strip()}"
        )
    checkpoint = _authority_state(database)
    if (
        len(checkpoint["jobs"]) != 1
        or checkpoint["jobs"][0]["state"] != "PREPARED"
        or checkpoint["metadata_artifacts"] != 0
        or checkpoint["lineage_rows"] != 0
    ):
        raise DemoFailure(f"unexpected persisted checkpoint: {checkpoint}")
    checkpoint_job = checkpoint["jobs"][0]["job_id"]

    resumed = _invoke_worker(database, spool)
    _expect_summary(resumed, prepared_resumed=1)
    verification = _verify_completion(database, spool, artifact_id, output_root)
    if verification["job_id"] != checkpoint_job:
        raise DemoFailure("resume completed a different deterministic job")
    replay = _invoke_worker(database, spool)
    _expect_summary(replay, already_complete=1)
    final = _authority_state(database)
    if len(final["jobs"]) != 1 or final["jobs"][0]["job_id"] != checkpoint_job:
        raise DemoFailure("resume duplicated or replaced the prepared job")

    receipt = {
        "schema_version": 1,
        "scenario": "resume",
        "proof_class": "standalone_synthetic_processing_resume",
        "status": "pass",
        "input": {
            "artifact_id": artifact_id,
            "media_path": _relative(input_media, output_root),
            "media_sha256": _sha256(input_media),
        },
        "interruption": {
            "exit_code": interrupted.returncode,
            "barrier": "after_prepared_commit",
            "checkpoint_job_id": checkpoint_job,
            "checkpoint_state": "PREPARED",
            "metadata_artifacts_before_resume": checkpoint["metadata_artifacts"],
            "lineage_rows_before_resume": checkpoint["lineage_rows"],
        },
        "worker_runs": {"resume": resumed, "replay": replay},
        "verification": verification,
        "final_authority": final,
        "invariants": {
            "checkpoint_persisted": True,
            "same_job_resumed": True,
            "completed_work_not_duplicated": True,
            "replay_idempotent": True,
        },
    }
    _write_scenario(output_root, "resume", receipt)
    return receipt


def _run_busy_lock(output_root: Path, fixture_media: Path) -> dict[str, Any]:
    from apps.edge_agent.lock import spool_lock

    database, spool, input_media, artifact_id = _prepare_case(
        output_root, "busy-lock", fixture_media
    )
    before = _authority_state(database)
    with spool_lock(spool, mode="exclusive"):
        blocked = _invoke_worker(database, spool)
    _expect_summary(
        blocked,
        status="deferred",
        deferred=1,
        remaining=1,
    )
    after_blocked = _authority_state(database)
    if after_blocked != before:
        raise DemoFailure("busy-lock attempt changed authoritative database state")

    retry = _invoke_worker(database, spool)
    _expect_summary(retry, newly_completed=1)
    verification = _verify_completion(database, spool, artifact_id, output_root)
    replay = _invoke_worker(database, spool)
    _expect_summary(replay, already_complete=1)
    final = _authority_state(database)
    receipt = {
        "schema_version": 1,
        "scenario": "busy-lock",
        "proof_class": "standalone_synthetic_processing_busy_lock",
        "status": "pass",
        "input": {
            "artifact_id": artifact_id,
            "media_path": _relative(input_media, output_root),
            "media_sha256": _sha256(input_media),
        },
        "before": before,
        "after_blocked": after_blocked,
        "worker_runs": {"blocked": blocked, "retry": retry, "replay": replay},
        "verification": verification,
        "final_authority": final,
        "invariants": {
            "canonical_lock_held": True,
            "blocked_attempt_deferred": True,
            "blocked_attempt_zero_write": True,
            "retry_completed": True,
            "replay_idempotent": True,
        },
    }
    _write_scenario(output_root, "busy-lock", receipt)
    return receipt


def _aggregate_summary_text(receipts: dict[str, dict[str, Any]]) -> str:
    lines = [
        "processor-worker reliability demo",
        "=================================",
        "Synthetic inputs only; no network, credentials, services, models, or publication.",
        "",
    ]
    for name in SCENARIOS:
        receipt = receipts[name]
        runs = receipt["worker_runs"]
        lines.append(f"[{name}] status={receipt['status']}")
        for label, summary in runs.items():
            lines.append(
                f"  {label:<8} status={summary['status']:<8} "
                f"new={summary['newly_completed']} resumed={summary['prepared_resumed']} "
                f"existing={summary['already_complete']} deferred={summary['deferred']} "
                f"remaining={summary['remaining']}"
            )
        lines.append(f"  receipt  {name}/receipt.json")
        lines.append("")
    lines.append("Inspect with: make inspect")
    return "\n".join(lines) + "\n"


def run_demo(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    if output_root == Path(output_root.anchor):
        raise DemoFailure("refusing to use filesystem root as demo output")
    shutil.rmtree(output_root, ignore_errors=True)
    output_root.mkdir(parents=True)
    fixture_media = output_root / "fixture" / "synthetic.mp4"
    _generate_media(fixture_media)

    receipts = {
        "normal": _run_normal(output_root, fixture_media),
        "resume": _run_resume(output_root, fixture_media),
        "busy-lock": _run_busy_lock(output_root, fixture_media),
    }
    aggregate = {
        "schema_version": 1,
        "proof_class": "standalone_synthetic_processing_reliability",
        "status": "pass",
        "constraints": {
            "synthetic_inputs_only": True,
            "network_required": False,
            "credentials_required": False,
            "external_service_required": False,
            "model_required": False,
            "publication_performed": False,
        },
        "scenarios": receipts,
        "output_structure": {
            "root": ".demo-output",
            "scenario_directories": list(SCENARIOS),
            "persistent": True,
            "inspect_command": "make inspect",
        },
    }
    _write_json(output_root / "summary.json", aggregate)
    summary_text = _aggregate_summary_text(receipts)
    (output_root / "summary.txt").write_text(summary_text, encoding="utf-8")
    print(summary_text, end="")
    print(json.dumps(aggregate, sort_keys=True, separators=(",", ":")))
    return aggregate


def _tree_lines(output_root: Path) -> list[str]:
    lines: list[str] = []
    for path in sorted(output_root.rglob("*")):
        relative = path.relative_to(output_root).as_posix()
        if path.is_dir():
            lines.append(f"d {relative}/")
        elif path.is_file():
            lines.append(f"f {relative} ({path.stat().st_size} bytes)")
    return lines


def inspect_demo(output_root: Path) -> None:
    summary_path = output_root / "summary.json"
    if not summary_path.is_file():
        raise DemoFailure("demo output is missing; run 'make demo' first")
    aggregate = json.loads(summary_path.read_text(encoding="utf-8"))
    print((output_root / "summary.txt").read_text(encoding="utf-8"), end="")
    print("Generated .demo-output structure")
    print("--------------------------------")
    for line in _tree_lines(output_root):
        print(line)
    print("\nMachine summary")
    print("---------------")
    print(json.dumps(aggregate, sort_keys=True, indent=2))


def deterministic_fingerprint(output_root: Path) -> dict[str, str]:
    if not (output_root / "summary.json").is_file():
        raise DemoFailure("demo output is missing; run 'make demo' first")
    result: dict[str, str] = {}
    for path in sorted(output_root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == ".edge-agent.lock" or path.suffix in {".sqlite3", ".mp4"}:
            continue
        relative = path.relative_to(output_root).as_posix()
        result[relative] = _sha256(path)
    return result


def clean_demo(output_root: Path) -> None:
    shutil.rmtree(output_root, ignore_errors=True)
    print(f"removed {output_root}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("demo", help="run all persistent reliability scenarios")
    subparsers.add_parser("inspect", help="inspect existing persistent output")
    subparsers.add_parser("fingerprint", help="hash deterministic demonstration files")
    subparsers.add_parser("clean", help="remove persistent demonstration output")
    interrupted = subparsers.add_parser("_interrupt-child", help=argparse.SUPPRESS)
    interrupted.add_argument("--database", required=True, type=Path)
    interrupted.add_argument("--spool-root", required=True, type=Path)
    interrupted.add_argument("--artifact-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "demo"
    try:
        if command == "demo":
            run_demo(args.output_root)
        elif command == "inspect":
            inspect_demo(args.output_root.resolve())
        elif command == "fingerprint":
            print(
                json.dumps(
                    deterministic_fingerprint(args.output_root.resolve()),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        elif command == "clean":
            clean_demo(args.output_root.resolve())
        elif command == "_interrupt-child":
            return _interrupt_child(args.database, args.spool_root, args.artifact_id)
        else:  # pragma: no cover - argparse owns command validation
            raise DemoFailure(f"unknown command: {command}")
    except DemoFailure as exc:
        print(f"demo error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
