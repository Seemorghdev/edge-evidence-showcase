#!/usr/bin/env python3
"""Replicate one verified processor report inside the isolated replication environment."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from apps.replication_worker import cli as replication_cli
from packages.database.migrations import migrate
from packages.replication import worker as replication_worker
from packages.replication.adapters.nfs import filesystem as nfs_filesystem

ROOT = Path(__file__).resolve().parents[1]
_OUTPUT_NAME = re.compile(r"^\.demo-output(?:-[a-z0-9][a-z0-9._-]*)?$")
TARGET_ID = "showcase-local-target"
STARTED_AT = "2026-08-26T10:00:00Z"
COMPLETED_AT = "2026-08-26T10:00:01Z"


class HandoffFailure(RuntimeError):
    """The processor-to-replication handoff failed closed."""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative_uri(root: Path, uri: str) -> Path:
    if not uri.startswith("file:"):
        raise HandoffFailure("replication URI was not a relative file URI")
    relative = Path(uri[5:])
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise HandoffFailure("replication URI was not canonical")
    return root.joinpath(*relative.parts)


def _reject_symlink_components(root: Path, target: Path) -> None:
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise HandoffFailure(f"symlink component is forbidden: {part}")


def _prepare_output(path: Path) -> Path:
    root = ROOT.resolve(strict=True)
    raw = path.expanduser()
    if ".." in raw.parts or ".git" in raw.parts:
        raise HandoffFailure("handoff output contains a protected path component")
    lexical = raw if raw.is_absolute() else root / raw
    lexical = Path(os.path.abspath(lexical))
    demo_root = lexical.parent
    replication_boundary = demo_root / "replication"

    if lexical.name != "handoff":
        raise HandoffFailure("handoff output must use the generated handoff directory")
    if demo_root.parent != root or not _OUTPUT_NAME.fullmatch(demo_root.name):
        raise HandoffFailure(
            "handoff output must be beside an exact generated .demo-output*/replication boundary"
        )
    _reject_symlink_components(root, lexical)
    _reject_symlink_components(root, replication_boundary)

    resolved_demo = demo_root.resolve(strict=False)
    resolved_replication = replication_boundary.resolve(strict=False)
    if resolved_demo.parent != root or resolved_replication != resolved_demo / "replication":
        raise HandoffFailure("resolved handoff output escapes the generated showcase")
    if not replication_boundary.is_dir():
        raise HandoffFailure("generated replication boundary is absent")
    if lexical.exists() or lexical.is_symlink():
        raise HandoffFailure("handoff output must be absent; refusing to remove existing state")
    lexical.mkdir()
    return lexical


def _seed_processor_output(
    database: Path,
    spool: Path,
    source_path: Path,
) -> dict[str, object]:
    data = source_path.read_bytes()
    digest = _sha(data)
    recording_id = f"sha256:{digest}"
    storage_uri = f"file:recordings/sha256/{digest[:2]}/{digest}.source"
    spool_path = _safe_relative_uri(spool, storage_uri)
    spool_path.parent.mkdir(parents=True, exist_ok=True)
    spool_path.write_bytes(data)

    descriptor = _canonical(
        {
            "clock_domain": "not_applicable",
            "source_kind": "synthetic_processor_output",
        }
    )
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO recording_imports ("
            "recording_id, source_id, source_descriptor_json, "
            "source_descriptor_sha256, byte_size, digest_algorithm, digest_value, "
            "storage_uri, recording_started_at, time_authority, state"
            ") VALUES (?, 'synthetic-processor', ?, ?, ?, 'sha256', ?, ?, ?, "
            "'operator_asserted_utc', 'PREPARED')",
            (
                recording_id,
                descriptor,
                _sha(descriptor.encode("utf-8")),
                len(data),
                digest,
                storage_uri,
                STARTED_AT,
            ),
        )
        connection.execute(
            "UPDATE recording_imports SET "
            "state='COMPLETE', container_class='iso_bmff_mp4', major_brand='isom', "
            "video_stream_index=0, video_codec='h264', pixel_format='yuv420p', "
            "coded_width=1280, coded_height=720, duration_ms=10000, "
            "display_rotation_ccw_degrees=0, completed_at=? "
            "WHERE recording_id=?",
            (COMPLETED_AT, recording_id),
        )
        connection.commit()
    return {
        "recording_id": recording_id,
        "storage_uri": storage_uri,
        "byte_size": len(data),
        "sha256": digest,
    }


def _invoke(arguments: list[str]) -> tuple[int, dict[str, Any]]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = replication_cli.main(arguments)
    output = stderr.getvalue() if code else stdout.getvalue()
    other = stdout.getvalue() if code else stderr.getvalue()
    if other.strip():
        raise HandoffFailure("replication worker emitted output on the unexpected stream")
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise HandoffFailure("replication worker did not emit exactly one JSON object")
    payload = json.loads(lines[0])
    if not isinstance(payload, dict):
        raise HandoffFailure("replication worker output was not a JSON object")
    return code, payload


def _authority_row(database: Path) -> dict[str, object]:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT relative_uri, expected_byte_size, expected_sha256, state, "
            "attempt_count, last_error FROM replica_objects WHERE target_id=?",
            (TARGET_ID,),
        ).fetchone()
    if row is None:
        raise HandoffFailure("replication authority row was not created")
    return {
        "relative_uri": str(row[0]),
        "expected_byte_size": int(row[1]),
        "expected_sha256": str(row[2]),
        "state": str(row[3]),
        "attempt_count": int(row[4]),
        "last_error": None if row[5] is None else str(row[5]),
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(_canonical(payload) + "\n", encoding="utf-8")


def _manifest(root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix == ".sqlite3":
            files.append(
                {
                    "path": relative,
                    "kind": "inspectable_sqlite_authority",
                    "byte_size": path.stat().st_size,
                }
            )
        else:
            data = path.read_bytes()
            files.append(
                {
                    "path": relative,
                    "kind": "deterministic_file",
                    "byte_size": len(data),
                    "sha256": _sha(data),
                }
            )
    return {"schema_version": 1, "status": "pass", "files": files}


def run(source: Path, source_label: str, output_dir: Path) -> dict[str, object]:
    source = source.resolve(strict=True)
    root = _prepare_output(output_dir)
    database = root / "authority.sqlite3"
    spool = root / "spool"
    target = root / "target"
    spool.mkdir()
    target.mkdir()
    migration = migrate(database)
    if migration.current_version != 10:
        raise HandoffFailure("fresh replication authority did not reach schema version 10")
    seeded = _seed_processor_output(database, spool, source)

    original_mount_probe = nfs_filesystem.mounted_fstype
    nfs_filesystem.mounted_fstype = lambda _root: "nfs4"
    try:
        replication_worker.init_target(database, target, TARGET_ID)
        run_code, first = _invoke(
            [
                "run",
                "--database",
                str(database),
                "--spool-root",
                str(spool),
                "--target-root",
                str(target),
                "--target-id",
                TARGET_ID,
            ]
        )
        verify_code, verification = _invoke(
            [
                "verify",
                "--database",
                str(database),
                "--target-root",
                str(target),
                "--target-id",
                TARGET_ID,
            ]
        )
        replay_code, replay = _invoke(
            [
                "run",
                "--database",
                str(database),
                "--spool-root",
                str(spool),
                "--target-root",
                str(target),
                "--target-id",
                TARGET_ID,
            ]
        )
    finally:
        nfs_filesystem.mounted_fstype = original_mount_probe

    expected_first = {
        "status": "pass",
        "discovered": 1,
        "inserted": 1,
        "published": 1,
        "adopted": 0,
        "verified": 1,
        "partials_cleaned": 0,
    }
    expected_verify = {
        "status": "pass",
        "discovered": 0,
        "inserted": 0,
        "published": 0,
        "adopted": 0,
        "verified": 1,
        "partials_cleaned": 0,
    }
    expected_replay = {
        "status": "pass",
        "discovered": 1,
        "inserted": 0,
        "published": 0,
        "adopted": 0,
        "verified": 0,
        "partials_cleaned": 0,
    }
    if run_code != 0 or first != expected_first:
        raise HandoffFailure(f"unexpected integrated replication run: {first}")
    if verify_code != 0 or verification != expected_verify:
        raise HandoffFailure(f"unexpected integrated verification: {verification}")
    if replay_code != 0 or replay != expected_replay:
        raise HandoffFailure(f"unexpected integrated replay: {replay}")

    authority = _authority_row(database)
    target_path = _safe_relative_uri(target, str(authority["relative_uri"]))
    target_bytes = target_path.read_bytes()
    observed_sha = _sha(target_bytes)
    invariants = {
        "processor_output_was_replication_source": seeded["sha256"]
        == authority["expected_sha256"],
        "immutable_create_performed": first["published"] == 1,
        "independent_readback_verified": verification["verified"] == 1,
        "target_bytes_match_processor_output": (
            target_bytes == source.read_bytes()
            and observed_sha == seeded["sha256"]
            and len(target_bytes) == seeded["byte_size"]
        ),
        "exact_replay_is_noop": replay["published"] == 0
        and replay["adopted"] == 0
        and replay["inserted"] == 0,
        "zero_unresolved_work": authority["state"] == "VERIFIED"
        and authority["last_error"] is None,
        "synthetic_nfs_contract_only": True,
    }
    if not all(invariants.values()):
        raise HandoffFailure(f"integrated handoff invariant failure: {invariants}")

    receipt: dict[str, object] = {
        "schema_version": 1,
        "proof_class": "integrated_synthetic_processor_output_replication",
        "status": "pass",
        "source": {
            "processor_output_artifact_id": seeded["recording_id"],
            "path": source_label,
            "byte_size": seeded["byte_size"],
            "sha256": seeded["sha256"],
        },
        "replication": {
            "target_id": TARGET_ID,
            "first_run": first,
            "verification": verification,
            "replay": replay,
            "authority": authority,
            "target_path": target_path.relative_to(root).as_posix(),
            "target_byte_size": len(target_bytes),
            "target_sha256": observed_sha,
        },
        "constraints": {
            "network_required": False,
            "credentials_required": False,
            "external_service_required": False,
            "model_required": False,
            "publication_performed": False,
        },
        "invariants": invariants,
    }
    _write_json(root / "summary.json", receipt)
    human = "\n".join(
        [
            "Integrated processor-output replication: PASS",
            f"Processor report: {source_label}",
            f"SHA-256: {seeded['sha256']}",
            f"Replication: created={first['published']} verified={verification['verified']}",
            f"Target: {receipt['replication']['target_path']}",
            "Replay: no new writes",
            "Scope: synthetic local NFS contract only",
            "",
        ]
    )
    (root / "summary.txt").write_text(human, encoding="utf-8")
    _write_json(root / "manifest.json", _manifest(root))
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = run(args.source, args.source_label, args.output_dir)
    except (HandoffFailure, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"handoff error: {exc}", file=sys.stderr)
        return 2
    print(_canonical(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
