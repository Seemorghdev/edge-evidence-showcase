"""Deterministic local demonstration for the exported replication worker."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Iterable

from apps.replication_worker import cli as replication_cli
from packages.database.migrations import migrate
from packages.replication import worker as replication_worker
from packages.replication.adapters.nfs import filesystem as nfs_filesystem
from packages.replication.adapters.nfs.model import (
    ADAPTER_KIND,
    TARGET_MARKER_NAME,
    owned_partial_name,
)
from packages.replication.core import authority as replication_authority

_TARGET_ID = "demo-target"
_STARTED = "2026-08-17T10:00:00Z"
_COMPLETED = "2026-08-17T10:00:10Z"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _relative_path(root: Path, uri: str) -> Path:
    if not uri.startswith("file:"):
        raise SystemExit("replication demo URI was not a relative file URI")
    relative = Path(uri[5:])
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise SystemExit("replication demo URI was not canonical")
    return root.joinpath(*relative.parts)


def _prepare_output(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    cwd = Path.cwd().resolve()
    if resolved in {Path(resolved.anchor), cwd, cwd.parent} or ".git" in resolved.parts:
        raise SystemExit("refusing unsafe demo output directory")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)
    return resolved


def _seed_recording(
    database: Path,
    spool: Path,
    *,
    source_id: str,
    data: bytes,
) -> dict[str, object]:
    digest = _sha256(data)
    recording_id = f"sha256:{digest}"
    storage_uri = f"file:recordings/sha256/{digest[:2]}/{digest}.source"
    source = _relative_path(spool, storage_uri)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)

    descriptor = _canonical_json(
        {"clock_domain": "unknown", "source_kind": "synthetic_local"}
    )
    descriptor_sha256 = _sha256(descriptor.encode("utf-8"))

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO recording_imports ("
            "recording_id, source_id, source_descriptor_json, "
            "source_descriptor_sha256, byte_size, digest_algorithm, digest_value, "
            "storage_uri, recording_started_at, time_authority, state"
            ") VALUES (?, ?, ?, ?, ?, 'sha256', ?, ?, ?, "
            "'operator_asserted_utc', 'PREPARED')",
            (
                recording_id,
                source_id,
                descriptor,
                descriptor_sha256,
                len(data),
                digest,
                storage_uri,
                _STARTED,
            ),
        )
        connection.execute(
            "UPDATE recording_imports SET "
            "state='COMPLETE', container_class='iso_bmff_mp4', major_brand='isom', "
            "video_stream_index=0, video_codec='h264', pixel_format='yuv420p', "
            "coded_width=1280, coded_height=720, duration_ms=10000, "
            "display_rotation_ccw_degrees=0, completed_at=? "
            "WHERE recording_id=?",
            (_COMPLETED, recording_id),
        )
        connection.commit()
    return {
        "source_id": source_id,
        "storage_uri": storage_uri,
        "byte_size": len(data),
        "sha256": digest,
    }


def _invoke(arguments: list[str]) -> tuple[int, dict[str, object]]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = replication_cli.main(arguments)

    output = stderr.getvalue() if code else stdout.getvalue()
    other = stdout.getvalue() if code else stderr.getvalue()
    if other.strip():
        raise SystemExit("replication-worker emitted output on the unexpected stream")
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SystemExit("replication-worker did not emit exactly one JSON object")
    payload = json.loads(lines[0])
    if not isinstance(payload, dict):
        raise SystemExit("replication-worker output was not a JSON object")
    return code, payload


def _target_metadata(database: Path, target: Path) -> dict[str, object]:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT target_id, adapter_kind, marker_sha256 "
            "FROM replica_targets WHERE target_id=?",
            (_TARGET_ID,),
        ).fetchone()
    if row is None:
        raise SystemExit("canonical target authority row was not created")
    marker_path = target / TARGET_MARKER_NAME
    marker_bytes = marker_path.read_bytes()
    marker = json.loads(marker_bytes)
    return {
        "target_id": str(row[0]),
        "adapter_kind": str(row[1]),
        "marker_sha256": str(row[2]),
        "marker_relative_path": f"target/{TARGET_MARKER_NAME}",
        "marker_document": marker,
        "marker_content_sha256": _sha256(marker_bytes),
    }


def _authority_objects(database: Path) -> list[dict[str, object]]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT object_kind, relative_uri, expected_byte_size, expected_sha256, "
            "state, attempt_count, last_error "
            "FROM replica_objects WHERE target_id=? "
            "ORDER BY object_kind, relative_uri",
            (_TARGET_ID,),
        ).fetchall()
    return [
        {
            "object_kind": str(kind),
            "relative_uri": str(uri),
            "expected_byte_size": int(size),
            "expected_sha256": str(digest),
            "state": str(state),
            "attempt_count": int(attempt_count),
            "last_error": None if last_error is None else str(last_error),
        }
        for kind, uri, size, digest, state, attempt_count, last_error in rows
    ]


def _authority_fingerprint(database: Path) -> str:
    return _sha256(_canonical_json(_authority_objects(database)).encode("utf-8"))


def _readback(target: Path, authority_rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in authority_rows:
        path = _relative_path(target, str(row["relative_uri"]))
        data = path.read_bytes()
        observed = _sha256(data)
        expected = str(row["expected_sha256"])
        expected_size = int(row["expected_byte_size"])
        result.append(
            {
                "object_kind": row["object_kind"],
                "relative_uri": row["relative_uri"],
                "authority_state": row["state"],
                "expected_byte_size": expected_size,
                "observed_byte_size": len(data),
                "expected_sha256": expected,
                "observed_sha256": observed,
                "identity_and_content_match": (
                    observed == expected and len(data) == expected_size
                ),
            }
        )
    return result


def _run_success_case(root: Path) -> dict[str, object]:
    database = root / "authority.sqlite3"
    spool = root / "spool"
    target = root / "target"
    spool.mkdir(parents=True)
    target.mkdir()
    migration = migrate(database)
    if migration.current_version != 10:
        raise SystemExit("replication export did not create schema-v10 authority")

    adopted_input = _seed_recording(
        database,
        spool,
        source_id="demo-adopt",
        data=b"already-present-replica\n",
    )
    created_input = _seed_recording(
        database,
        spool,
        source_id="demo-create",
        data=b"new-immutable-replica\n",
    )

    marker_preexisting = (target / TARGET_MARKER_NAME).exists()
    with sqlite3.connect(database) as connection:
        row_preexisting = connection.execute(
            "SELECT 1 FROM replica_targets WHERE target_id=?", (_TARGET_ID,)
        ).fetchone() is not None
    replication_worker.init_target(database, target, _TARGET_ID)
    created_metadata = _target_metadata(database, target)
    replication_worker.init_target(database, target, _TARGET_ID)
    adopted_metadata = _target_metadata(database, target)
    if created_metadata != adopted_metadata:
        raise SystemExit("target re-adoption changed canonical metadata")

    objects = replication_authority.discover(database, spool, _TARGET_ID)
    with replication_authority.connect(database) as connection:
        inserted = replication_authority.register_discovered(
            connection, _TARGET_ID, objects
        )
    if inserted != 2:
        raise SystemExit("replication demo did not register exactly two objects")

    by_uri = {item.relative_uri: item for item in objects}
    adopted_object = by_uri[str(adopted_input["storage_uri"])]
    created_object = by_uri[str(created_input["storage_uri"])]
    adopted_final = nfs_filesystem.ensure_destination_parent(
        target, str(adopted_input["storage_uri"])
    )
    adopted_final.write_bytes(b"already-present-replica\n")
    created_final = nfs_filesystem.ensure_destination_parent(
        target, str(created_input["storage_uri"])
    )
    partial = created_final.parent / owned_partial_name(created_object)
    partial.write_bytes(b"owned-transient-partial")
    partial_existed_before = partial.exists()

    code, first = _invoke(
        [
            "run",
            "--database",
            str(database),
            "--spool-root",
            str(spool),
            "--target-root",
            str(target),
            "--target-id",
            _TARGET_ID,
        ]
    )
    expected_first = {
        "status": "pass",
        "discovered": 2,
        "inserted": 0,
        "published": 1,
        "adopted": 1,
        "verified": 2,
        "partials_cleaned": 1,
    }
    if code != 0 or first != expected_first:
        raise SystemExit(f"unexpected first replication summary: {first}")

    verify_code, verification = _invoke(
        [
            "verify",
            "--database",
            str(database),
            "--target-root",
            str(target),
            "--target-id",
            _TARGET_ID,
        ]
    )
    expected_verification = {
        "status": "pass",
        "discovered": 0,
        "inserted": 0,
        "published": 0,
        "adopted": 0,
        "verified": 2,
        "partials_cleaned": 0,
    }
    if verify_code != 0 or verification != expected_verification:
        raise SystemExit(f"unexpected replication verification summary: {verification}")

    rows_before_rerun = _authority_objects(database)
    fingerprint_before = _authority_fingerprint(database)
    second_code, second = _invoke(
        [
            "run",
            "--database",
            str(database),
            "--spool-root",
            str(spool),
            "--target-root",
            str(target),
            "--target-id",
            _TARGET_ID,
        ]
    )
    expected_second = {
        "status": "pass",
        "discovered": 2,
        "inserted": 0,
        "published": 0,
        "adopted": 0,
        "verified": 0,
        "partials_cleaned": 0,
    }
    if second_code != 0 or second != expected_second:
        raise SystemExit(f"unexpected exact-rerun summary: {second}")
    rows_after_rerun = _authority_objects(database)
    fingerprint_after = _authority_fingerprint(database)

    readback = _readback(target, rows_after_rerun)
    if not all(item["identity_and_content_match"] for item in readback):
        raise SystemExit("target readback did not match canonical authority")

    return {
        "database_schema_version": migration.current_version,
        "target_lifecycle": {
            "initial_path": "created",
            "marker_preexisting": marker_preexisting,
            "authority_row_preexisting": row_preexisting,
            "repeat_path": "adopted_existing",
            "metadata_unchanged_on_repeat": created_metadata == adopted_metadata,
        },
        "target": created_metadata,
        "synthetic_inputs": [adopted_input, created_input],
        "registered_objects": inserted,
        "first_run": first,
        "verification": verification,
        "readback": readback,
        "cleanup": {
            "transient_kind": "worker_owned_partial",
            "partial_name": partial.name,
            "existed_before": partial_existed_before,
            "exists_after": partial.exists(),
            "reported_cleaned": first["partials_cleaned"],
        },
        "rerun": {
            "summary": second,
            "authority_state_sha256_before": fingerprint_before,
            "authority_state_sha256_after": fingerprint_after,
            "authority_rows_unchanged": rows_before_rerun == rows_after_rerun,
        },
        "final_authority": rows_after_rerun,
        "adopted_object_uri": adopted_object.relative_uri,
        "created_object_uri": created_object.relative_uri,
    }


def _run_collision_case(root: Path) -> dict[str, object]:
    database = root / "authority.sqlite3"
    spool = root / "spool"
    target = root / "target"
    spool.mkdir(parents=True)
    target.mkdir()
    migrate(database)
    seeded = _seed_recording(
        database,
        spool,
        source_id="demo-collision",
        data=b"expected-replica-bytes\n",
    )
    replication_worker.init_target(database, target, _TARGET_ID)
    final = nfs_filesystem.ensure_destination_parent(
        target, str(seeded["storage_uri"])
    )
    wrong = b"pre-existing-wrong-bytes\n"
    final.write_bytes(wrong)

    code, payload = _invoke(
        [
            "run",
            "--database",
            str(database),
            "--spool-root",
            str(spool),
            "--target-root",
            str(target),
            "--target-id",
            _TARGET_ID,
        ]
    )
    if code != 4 or payload != {
        "status": "error",
        "finding": "destination_collision",
    }:
        raise SystemExit(f"collision did not fail closed: {code}, {payload}")
    authority_rows = _authority_objects(database)
    return {
        "exit_code": code,
        "finding": payload["finding"],
        "relative_uri": seeded["storage_uri"],
        "expected_sha256": seeded["sha256"],
        "observed_conflicting_sha256": _sha256(wrong),
        "wrong_bytes_preserved": final.read_bytes() == wrong,
        "authority": authority_rows,
    }


def _render_human(receipt: dict[str, object]) -> str:
    success = receipt["success"]
    collision = receipt["collision"]
    lifecycle = success["target_lifecycle"]
    first = success["first_run"]
    rerun = success["rerun"]
    cleanup = success["cleanup"]
    lines = [
        "Replication worker deterministic local demo: PASS",
        "",
        f"Target: {success['target']['target_id']} ({success['target']['adapter_kind']})",
        f"Target lifecycle: {lifecycle['initial_path']} -> {lifecycle['repeat_path']}",
        (
            "First run: "
            f"adopted={first['adopted']} created={first['published']} "
            f"verified={first['verified']}"
        ),
        f"Readback: {len(success['readback'])} objects matched identity and content",
        (
            "Cleanup: "
            f"partial existed={str(cleanup['existed_before']).lower()} "
            f"remaining={str(cleanup['exists_after']).lower()}"
        ),
        (
            "Rerun: no new writes; authority unchanged="
            f"{str(rerun['authority_rows_unchanged']).lower()}"
        ),
        (
            "Collision: refused with "
            f"{collision['finding']} (exit {collision['exit_code']}); "
            f"conflicting bytes preserved={str(collision['wrong_bytes_preserved']).lower()}"
        ),
        "",
        "Machine summary: .demo-output/summary.json",
        "Inspectable state: .demo-output/success and .demo-output/collision",
    ]
    return "\n".join(lines) + "\n"


def _evidence_manifest(root: Path) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix == ".sqlite3":
            records.append(
                {
                    "path": relative,
                    "kind": "inspectable_sqlite_authority",
                    "byte_size": path.stat().st_size,
                }
            )
            continue
        data = path.read_bytes()
        records.append(
            {
                "path": relative,
                "kind": "deterministic_file",
                "byte_size": len(data),
                "sha256": _sha256(data),
            }
        )
    deterministic = [item for item in records if item["kind"] == "deterministic_file"]
    return {
        "schema_version": 1,
        "status": "pass",
        "deterministic_files_sha256": _sha256(
            _canonical_json(deterministic).encode("utf-8")
        ),
        "files": records,
    }


def _run_demo_at(output: Path) -> dict[str, object]:
    root = _prepare_output(output)
    success_root = root / "success"
    collision_root = root / "collision"
    success_root.mkdir()
    collision_root.mkdir()

    original_mount_probe = nfs_filesystem.mounted_fstype
    nfs_filesystem.mounted_fstype = lambda _root: "nfs4"
    try:
        success = _run_success_case(success_root)
        collision = _run_collision_case(collision_root)
    finally:
        nfs_filesystem.mounted_fstype = original_mount_probe

    invariants = {
        "canonical_target_created_then_adopted": (
            success["target_lifecycle"]["initial_path"] == "created"
            and success["target_lifecycle"]["repeat_path"] == "adopted_existing"
            and success["target_lifecycle"]["metadata_unchanged_on_repeat"] is True
        ),
        "immutable_create_verified": success["first_run"]["published"] == 1,
        "exact_adoption_verified": success["first_run"]["adopted"] == 1,
        "independent_readback_verified": all(
            item["identity_and_content_match"] for item in success["readback"]
        ),
        "transient_cleanup_verified": (
            success["cleanup"]["existed_before"] is True
            and success["cleanup"]["exists_after"] is False
            and success["cleanup"]["reported_cleaned"] == 1
        ),
        "safe_rerun_is_noop": (
            success["rerun"]["summary"]["published"] == 0
            and success["rerun"]["summary"]["adopted"] == 0
            and success["rerun"]["summary"]["inserted"] == 0
            and success["rerun"]["authority_rows_unchanged"] is True
            and success["rerun"]["authority_state_sha256_before"]
            == success["rerun"]["authority_state_sha256_after"]
        ),
        "collision_fails_closed": (
            collision["exit_code"] == 4
            and collision["finding"] == "destination_collision"
            and collision["wrong_bytes_preserved"] is True
            and collision["authority"][0]["state"] == "PENDING"
            and collision["authority"][0]["last_error"] == "destination_collision"
        ),
        "local_synthetic_inputs_only": True,
        "zero_network_credentials_or_publication": True,
    }
    if not all(invariants.values()):
        raise SystemExit(f"replication demo invariant failure: {invariants}")

    receipt: dict[str, object] = {
        "schema_version": 2,
        "proof_class": "deterministic_local_replication",
        "status": "pass",
        "authority": {
            "database_schema_version": success["database_schema_version"],
            "target_id": _TARGET_ID,
            "adapter_kind": ADAPTER_KIND,
        },
        "success": success,
        "collision": collision,
        "invariants": invariants,
        "output": {
            "root": ".demo-output",
            "summary_json": ".demo-output/summary.json",
            "summary_text": ".demo-output/summary.txt",
            "manifest_json": ".demo-output/manifest.json",
        },
    }
    summary_json = _canonical_json(receipt) + "\n"
    (root / "summary.json").write_text(summary_json, encoding="utf-8")
    (root / "summary.txt").write_text(_render_human(receipt), encoding="utf-8")
    manifest = _evidence_manifest(root)
    (root / "manifest.json").write_text(
        _canonical_json(manifest) + "\n", encoding="utf-8"
    )
    return receipt


def run_demo(output_dir: Path | None = None) -> dict[str, object]:
    if output_dir is not None:
        return _run_demo_at(output_dir)
    with tempfile.TemporaryDirectory(prefix="replication-worker-demo-") as temp:
        return _run_demo_at(Path(temp) / ".demo-output")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".demo-output"),
        help="persistent local evidence directory (default: .demo-output)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the machine summary to stdout instead of the human summary",
    )
    args = parser.parse_args(argv)
    receipt = run_demo(args.output_dir)
    if args.json:
        print(_canonical_json(receipt))
    else:
        print(_render_human(receipt), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
