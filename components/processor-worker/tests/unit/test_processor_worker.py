"""Bounded processor-worker behavior and authority tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

from apps.edge_agent import finalize, process, verification
from apps.edge_agent.register import RegisterError
from apps.processor_worker import cli, worker
from packages.agent_contracts.canonical import canonical_sha256
from packages.agent_contracts.model import AuthorityReference, Service
from packages.database.migrations import migrate
from packages.processing import fingerprint

_START = "2026-08-11T10:00:00Z"
_END = "2026-08-11T10:00:10Z"


@pytest.fixture
def fake_ffprobe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verification, "require_tool", lambda name: None)
    monkeypatch.setattr(
        verification,
        "ffprobe_duration_seconds",
        lambda path: 10.0,
    )


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "ledger.sqlite3"
    migrate(database)
    spool = tmp_path / "spool"
    spool.mkdir()
    return database, spool


def _add_raw(
    database: Path,
    spool: Path,
    *,
    label: str,
    sequence: int,
    source_id: str = "cam-01",
) -> str:
    media = f"spec020-{label}-raw-media".encode("utf-8")
    digest = hashlib.sha256(media).hexdigest()
    artifact_id = f"sha256:{digest}"
    media_path = spool / finalize.media_relative_path(digest)
    manifest_path = spool / finalize.manifest_relative_path(digest)
    media_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(media)
    manifest = {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "source_id": source_id,
        "artifact_kind": "raw_media",
        "media_type": "video/mp4",
        "byte_size": len(media),
        "digest": {"algorithm": "sha256", "value": digest},
        "storage_uri": finalize.storage_uri(digest),
        "finalized_at": _END,
    }
    manifest_bytes = finalize.serialize_manifest(manifest)
    manifest_path.write_bytes(manifest_bytes)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    occurrence = f"occ-{label}"
    session = f"sess-{label}"

    connection = sqlite3.connect(database)
    try:
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
                len(media),
                digest,
                finalize.storage_uri(digest),
                f"file:manifests/sha256/{digest[:2]}/{digest}.json",
                manifest_sha,
                _END,
            ),
        )
        connection.execute(
            "INSERT INTO expected_occurrences (occurrence_id, source_id, session_id, "
            "sequence_number, expected_started_at, expected_ended_at, state, artifact_id, "
            "terminal_at) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETE', ?, ?)",
            (
                occurrence,
                source_id,
                session,
                sequence,
                _START,
                _END,
                artifact_id,
                _END,
            ),
        )
        connection.execute(
            "INSERT INTO capture_occurrences (occurrence_id, source_id, session_id, "
            "sequence_number, capture_started_at, capture_ended_at, artifact_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                occurrence,
                source_id,
                session,
                sequence,
                _START,
                _END,
                artifact_id,
            ),
        )
        connection.execute(
            "INSERT INTO capture_occurrence_assertions (occurrence_id, source_id, "
            "artifact_id, manifest_layout, manifest_uri, manifest_sha256, finalized_at) "
            "VALUES (?, ?, ?, 'legacy_digest_v1', ?, ?, ?)",
            (
                occurrence,
                source_id,
                artifact_id,
                f"file:manifests/sha256/{digest[:2]}/{digest}.json",
                manifest_sha,
                _END,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return artifact_id


def _add_second_assertion(
    database: Path,
    artifact_id: str,
    *,
    label: str,
) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        source_id, manifest_sha, finalized_at = connection.execute(
            "SELECT source_id, manifest_sha256, finalized_at "
            "FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        occurrence = f"occ-{label}"
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO expected_occurrences (occurrence_id, source_id, session_id, "
            "sequence_number, expected_started_at, expected_ended_at, state, artifact_id, "
            "terminal_at) VALUES (?, ?, ?, 99, ?, ?, 'COMPLETE', ?, ?)",
            (
                occurrence,
                source_id,
                f"sess-{label}",
                _START,
                _END,
                artifact_id,
                _END,
            ),
        )
        connection.execute(
            "INSERT INTO capture_occurrences (occurrence_id, source_id, session_id, "
            "sequence_number, capture_started_at, capture_ended_at, artifact_id) "
            "VALUES (?, ?, ?, 99, ?, ?, ?)",
            (
                occurrence,
                source_id,
                f"sess-{label}",
                _START,
                _END,
                artifact_id,
            ),
        )
        connection.execute(
            "INSERT INTO capture_occurrence_assertions (occurrence_id, source_id, "
            "artifact_id, manifest_layout, manifest_uri, manifest_sha256, finalized_at) "
            "VALUES (?, ?, ?, 'occurrence_v1', ?, ?, ?)",
            (
                occurrence,
                source_id,
                artifact_id,
                f"file:assertions/capture/{occurrence}.artifact-manifest.json",
                manifest_sha,
                finalized_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _job_count(database: Path) -> int:
    connection = sqlite3.connect(database)
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM processing_jobs"
            ).fetchone()[0]
        )
    finally:
        connection.close()


def test_snapshot_is_deterministic_and_excludes_multi_assertion(
    tmp_path: Path,
) -> None:
    database, spool = _setup(tmp_path)
    first = _add_raw(database, spool, label="z", sequence=1)
    second = _add_raw(database, spool, label="a", sequence=2)
    third = _add_raw(
        database,
        spool,
        label="multi",
        sequence=3,
    )
    _add_second_assertion(database, third, label="multi-2")

    candidates = worker.snapshot(database)
    assert [c.artifact_id for c in candidates] == sorted(
        [first, second]
    )
    assert {c.prior_state for c in candidates} == {"MISSING"}


def test_run_catches_up_missing_jobs_and_exact_rerun_is_empty(
    tmp_path: Path,
    fake_ffprobe: None,
) -> None:
    database, spool = _setup(tmp_path)
    _add_raw(database, spool, label="one", sequence=1)
    _add_raw(database, spool, label="two", sequence=2)

    first = worker.run(database, spool)
    assert first.public() == {
        "status": "pass",
        "snapshot_eligible": 2,
        "already_complete": 0,
        "prepared_resumed": 0,
        "newly_completed": 2,
        "deferred": 0,
        "remaining": 0,
    }
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT state, processor_name, processor_version, "
            "output_contract, parameters_json "
            "FROM processing_jobs ORDER BY job_id"
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == 2
    assert all(row[0] == "COMPLETE" for row in rows)
    assert all(
        row[1] == fingerprint.PROCESSOR_NAME
        for row in rows
    )
    assert all(
        row[2] == fingerprint.PROCESSOR_VERSION
        for row in rows
    )
    assert all(
        row[3] == fingerprint.OUTPUT_CONTRACT
        for row in rows
    )
    assert all(
        json.loads(row[4]) == {"profile": "integrity"}
        for row in rows
    )

    second = worker.run(database, spool)
    assert second.snapshot_eligible == 2
    assert second.already_complete == 2
    assert second.prepared_resumed == 0
    assert second.newly_completed == 0
    assert second.deferred == 0
    assert second.remaining == 0
    assert _job_count(database) == 2


def test_prepared_job_is_resumed_by_worker(
    tmp_path: Path,
    fake_ffprobe: None,
) -> None:
    database, spool = _setup(tmp_path)
    artifact_id = _add_raw(
        database,
        spool,
        label="prepared",
        sequence=1,
    )

    def stop_after_prepared() -> None:
        raise RuntimeError("test barrier")

    process.set_barrier(
        "after_prepared_commit",
        stop_after_prepared,
    )
    try:
        with pytest.raises(RuntimeError, match="test barrier"):
            process.process_artifact(
                process.ProcessRequest(
                    database_path=str(database),
                    spool_root=str(spool),
                    input_artifact_id=artifact_id,
                    profile="integrity",
                )
            )
    finally:
        process.reset_barriers()

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT state FROM processing_jobs"
        ).fetchall() == [("PREPARED",)]
    finally:
        connection.close()

    summary = worker.run(database, spool)
    assert summary.prepared_resumed == 1
    assert summary.newly_completed == 0
    assert summary.remaining == 0
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT state FROM processing_jobs"
        ).fetchall() == [("COMPLETE",)]
    finally:
        connection.close()


def test_exact_lock_busy_is_deferred_and_does_not_create_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, spool = _setup(tmp_path)
    _add_raw(database, spool, label="busy", sequence=1)

    def busy(_request):
        raise RegisterError(
            "could not acquire spool lock within 5 s "
            "(another operation holds it)",
            code=7,
        )

    monkeypatch.setattr(
        worker.process_mod,
        "process_artifact",
        busy,
    )
    summary = worker.run(database, spool)
    assert summary.status == "deferred"
    assert summary.deferred == 1
    assert summary.remaining == 1
    assert summary.newly_completed == 0
    assert _job_count(database) == 0


def test_non_lock_failure_is_sanitized_by_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, spool = _setup(tmp_path)
    _add_raw(database, spool, label="private", sequence=1)

    def fail(_request):
        raise RegisterError(
            "database failed at /private/owner/path",
            code=7,
        )

    monkeypatch.setattr(
        worker.process_mod,
        "process_artifact",
        fail,
    )
    code = cli.main(
        [
            "run",
            "--database",
            str(database),
            "--spool-root",
            str(spool),
        ]
    )
    captured = capsys.readouterr()
    assert code == 7
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "error",
        "finding": "processing_database_failure",
    }
    assert "/private/owner/path" not in captured.err


def test_multi_assertion_artifact_creates_zero_worker_authority(
    tmp_path: Path,
    fake_ffprobe: None,
) -> None:
    database, spool = _setup(tmp_path)
    artifact_id = _add_raw(
        database,
        spool,
        label="multi-only",
        sequence=1,
    )
    _add_second_assertion(
        database,
        artifact_id,
        label="multi-only-2",
    )
    summary = worker.run(database, spool)
    assert summary.snapshot_eligible == 0
    assert summary.remaining == 0
    assert _job_count(database) == 0


def test_wrong_deterministic_job_id_fails_closed(
    tmp_path: Path,
) -> None:
    database, spool = _setup(tmp_path)
    artifact_id = _add_raw(
        database,
        spool,
        label="conflict",
        sequence=1,
    )
    params = fingerprint.canonical_parameters(
        "integrity"
    ).decode("utf-8")
    params_sha = fingerprint.parameters_sha256("integrity")
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO processing_jobs "
            "(job_id, input_artifact_id, processor_name, "
            "processor_version, output_contract, parameters_json, "
            "parameters_sha256, state) "
            "VALUES ('wrong-job-id', ?, ?, ?, ?, ?, ?, 'PREPARED')",
            (
                artifact_id,
                fingerprint.PROCESSOR_NAME,
                fingerprint.PROCESSOR_VERSION,
                fingerprint.OUTPUT_CONTRACT,
                params,
                params_sha,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(worker.ProcessorWorkerError) as exc:
        worker.snapshot(database)
    assert exc.value.finding == (
        "processing_job_identity_conflict"
    )
    assert exc.value.code == 4


@dataclass(frozen=True)
class _ExactContext:
    schema: ClassVar[str] = (
        "processor-authority-reconstruction-context.v1"
    )
    service: str
    canonical_repository: str
    canonical_commit: str
    authority_instance: str
    projection_schema: str
    contract_version: str
    database_schema_version: int
    proof_class: str
    implementation_identity_sha256: str


@dataclass(frozen=True)
class _ExactEntry:
    artifact_id: str
    deterministic_job_id: str
    input_digest_sha256: str
    prior_state: str


@dataclass(frozen=True)
class _ExactManifest:
    schema: ClassVar[str] = "processor-candidate-manifest.v3"
    authority_context_sha256: str
    authority_reference_sha256: str
    entries_digest_sha256: str
    entries: tuple[_ExactEntry, ...]


def _exact_inputs(
    database: Path,
    artifact_ids: tuple[str, ...] | None = None,
) -> tuple[_ExactContext, _ExactManifest]:
    context = _ExactContext(
        service="processor-worker",
        canonical_repository="private-redacted",
        canonical_commit="4" * 40,
        authority_instance=(
            "pms-b01-disposable-processor-authority"
        ),
        projection_schema="processor-candidate-manifest.v3",
        contract_version=(
            "processor-mutation-successor-freeze.v5"
        ),
        database_schema_version=10,
        proof_class="processor-exact-manifest-readback.v1",
        implementation_identity_sha256="5" * 64,
    )
    selected = {
        candidate.artifact_id: candidate
        for candidate in worker.snapshot(database)
    }
    ids = (
        tuple(sorted(selected))
        if artifact_ids is None
        else artifact_ids
    )
    entries = tuple(
        _ExactEntry(
            artifact_id=selected[artifact_id].artifact_id,
            deterministic_job_id=fingerprint.job_id_for(
                selected[artifact_id].digest_hex,
                "integrity",
            ),
            input_digest_sha256=selected[
                artifact_id
            ].digest_hex,
            prior_state=selected[artifact_id].prior_state,
        )
        for artifact_id in ids
    )
    entries_digest = canonical_sha256(entries)
    authority = AuthorityReference(
        service=Service.PROCESSOR,
        canonical_repository=context.canonical_repository,
        canonical_commit=context.canonical_commit,
        authority_instance=context.authority_instance,
        projection_schema=context.projection_schema,
        contract_version=context.contract_version,
        database_schema_version=context.database_schema_version,
        observed_snapshot_sha256=entries_digest,
        proof_class=context.proof_class,
    )
    return context, _ExactManifest(
        authority_context_sha256=canonical_sha256(context),
        authority_reference_sha256=authority.digest_sha256,
        entries_digest_sha256=entries_digest,
        entries=entries,
    )


def test_public_run_exact_is_available_without_adapter_import() -> None:
    assert callable(worker.run_exact)
    assert worker.run_exact.__module__ == (
        "apps.processor_worker.worker"
    )


def test_public_run_exact_rejects_manifest_drift_before_mutation(
    tmp_path: Path,
) -> None:
    database, spool = _setup(tmp_path)
    _add_raw(database, spool, label="exact-drift", sequence=1)
    context, approved = _exact_inputs(database)
    entry = approved.entries[0]
    changed_entry = _ExactEntry(
        artifact_id=entry.artifact_id,
        deterministic_job_id=entry.deterministic_job_id,
        input_digest_sha256=entry.input_digest_sha256,
        prior_state="PREPARED",
    )
    changed_entries = (changed_entry,)
    authority = AuthorityReference(
        service=Service.PROCESSOR,
        canonical_repository=context.canonical_repository,
        canonical_commit=context.canonical_commit,
        authority_instance=context.authority_instance,
        projection_schema=context.projection_schema,
        contract_version=context.contract_version,
        database_schema_version=context.database_schema_version,
        observed_snapshot_sha256=canonical_sha256(changed_entries),
        proof_class=context.proof_class,
    )
    changed = _ExactManifest(
        authority_context_sha256=canonical_sha256(context),
        authority_reference_sha256=authority.digest_sha256,
        entries_digest_sha256=canonical_sha256(changed_entries),
        entries=changed_entries,
    )
    with pytest.raises(
        worker.ProcessorWorkerError,
        match="approved_manifest_mismatch",
    ):
        worker.run_exact(database, spool, changed, context)
    assert _job_count(database) == 0


def test_public_run_exact_processes_only_approved_items(
    tmp_path: Path,
    fake_ffprobe: None,
) -> None:
    database, spool = _setup(tmp_path)
    approved_id = _add_raw(
        database,
        spool,
        label="approved-exact",
        sequence=1,
    )
    outside_id = _add_raw(
        database,
        spool,
        label="outside-exact",
        sequence=2,
    )
    context, approved = _exact_inputs(
        database,
        (approved_id,),
    )
    summary = worker.run_exact(
        database,
        spool,
        approved,
        context,
    )
    assert summary.snapshot_eligible == 1
    connection = sqlite3.connect(database)
    try:
        processed = {
            row[0]
            for row in connection.execute(
                "SELECT input_artifact_id FROM processing_jobs"
            )
        }
    finally:
        connection.close()
    assert processed == {approved_id}
    assert outside_id not in processed
