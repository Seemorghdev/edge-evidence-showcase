"""Bounded catch-up worker over existing processing authority.

The worker owns no new queue or state machine. One invocation takes a read-only
snapshot of currently eligible raw artifacts, then reuses the exact
``process_artifact`` orchestration for that frozen snapshot in deterministic order.

The bounded ``run_exact`` primitive validates one approved item set. It validates one approved item
manifest and authority context before mutation, then iterates only those approved
items. The historical ``run`` command and summary remain unchanged.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path

from apps.edge_agent import migration_history
from apps.edge_agent import process as process_mod
from apps.edge_agent.finalize import FinalizeError
from packages.agent_contracts.canonical import canonical_sha256
from packages.agent_contracts.model import AuthorityReference, Service
from packages.processing import fingerprint

_PROFILE = "integrity"
_SQLITE_TIMEOUT_SECONDS = 5.0
_LOCK_BUSY_MESSAGE = "could not acquire spool lock within 5 s (another operation holds it)"

_EXACT_CONTEXT_SCHEMA = "processor-authority-reconstruction-context.v1"
_EXACT_MANIFEST_SCHEMA = "processor-candidate-manifest.v3"
_EXACT_CONTRACT_VERSION = "processor-mutation-successor-freeze.v5"
_EXACT_PROOF_CLASS = "processor-exact-manifest-readback.v1"
_EXACT_AUTHORITY_INSTANCE = "pms-b01-disposable-processor-authority"
_EXACT_DATABASE_SCHEMA_VERSION = 10
_EXACT_CONTEXT_FIELDS = (
    "service",
    "canonical_repository",
    "canonical_commit",
    "authority_instance",
    "projection_schema",
    "contract_version",
    "database_schema_version",
    "proof_class",
    "implementation_identity_sha256",
)
_EXACT_MANIFEST_FIELDS = (
    "authority_context_sha256",
    "authority_reference_sha256",
    "entries_digest_sha256",
    "entries",
)
_EXACT_ENTRY_FIELDS = (
    "artifact_id",
    "deterministic_job_id",
    "input_digest_sha256",
    "prior_state",
)
_EXACT_PRIOR_STATES = frozenset({"MISSING", "PREPARED", "COMPLETE"})


class ProcessorWorkerError(Exception):
    """Path-neutral worker failure carrying one stable finding and exit code."""

    def __init__(self, finding: str, code: int) -> None:
        super().__init__(finding)
        self.finding = finding
        self.code = code


@dataclass(frozen=True)
class Candidate:
    artifact_id: str
    digest_hex: str
    prior_state: str  # MISSING | PREPARED | COMPLETE


@dataclass(frozen=True)
class RunSummary:
    snapshot_eligible: int
    already_complete: int
    prepared_resumed: int
    newly_completed: int
    deferred: int
    remaining: int
    status: str

    def public(self) -> dict[str, int | str]:
        return {
            "status": self.status,
            "snapshot_eligible": self.snapshot_eligible,
            "already_complete": self.already_complete,
            "prepared_resumed": self.prepared_resumed,
            "newly_completed": self.newly_completed,
            "deferred": self.deferred,
            "remaining": self.remaining,
        }


def _connect_readonly(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise ProcessorWorkerError("database_unavailable", code=7)
    try:
        connection = sqlite3.connect(
            database.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=_SQLITE_TIMEOUT_SECONDS,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(_SQLITE_TIMEOUT_SECONDS * 1000)}")
        return connection
    except (OSError, sqlite3.Error) as exc:
        raise ProcessorWorkerError("database_unavailable", code=7) from exc


def _require_authority(connection: sqlite3.Connection) -> None:
    try:
        if not migration_history.accepts_from(connection, 8):
            raise ProcessorWorkerError("database_migration_required", code=7)
        required = {"artifacts", "capture_occurrence_assertions", "processing_jobs"}
        present = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not required.issubset(present):
            raise ProcessorWorkerError("database_migration_required", code=7)
    except ProcessorWorkerError:
        raise
    except sqlite3.Error as exc:
        raise ProcessorWorkerError("database_integrity_failure", code=7) from exc


def _expected_identity(artifact_id: str) -> tuple[str, str, str, str, str, str]:
    return (
        artifact_id,
        fingerprint.PROCESSOR_NAME,
        fingerprint.PROCESSOR_VERSION,
        fingerprint.OUTPUT_CONTRACT,
        fingerprint.canonical_parameters(_PROFILE).decode("utf-8"),
        fingerprint.parameters_sha256(_PROFILE),
    )


def _job_state(
    connection: sqlite3.Connection,
    *,
    artifact_id: str,
    digest_hex: str,
) -> str:
    expected_job_id = fingerprint.job_id_for(digest_hex, _PROFILE)
    expected = _expected_identity(artifact_id)

    row = connection.execute(
        "SELECT input_artifact_id, processor_name, processor_version, output_contract, "
        "parameters_json, parameters_sha256, state FROM processing_jobs WHERE job_id = ?",
        (expected_job_id,),
    ).fetchone()
    if row is not None:
        if tuple(row[:6]) != expected:
            raise ProcessorWorkerError("processing_job_identity_conflict", code=4)
        state = str(row[6])
        if state not in ("PREPARED", "COMPLETE"):
            raise ProcessorWorkerError("processing_job_state_invalid", code=6)
        return state

    identity_row = connection.execute(
        "SELECT job_id, parameters_json, state FROM processing_jobs "
        "WHERE input_artifact_id = ? AND processor_name = ? AND processor_version = ? "
        "AND output_contract = ? AND parameters_sha256 = ?",
        (
            artifact_id,
            fingerprint.PROCESSOR_NAME,
            fingerprint.PROCESSOR_VERSION,
            fingerprint.OUTPUT_CONTRACT,
            fingerprint.parameters_sha256(_PROFILE),
        ),
    ).fetchone()
    if identity_row is not None:
        if (
            str(identity_row[0]) != expected_job_id
            or str(identity_row[1]) != expected[4]
        ):
            raise ProcessorWorkerError("processing_job_identity_conflict", code=4)
        state = str(identity_row[2])
        if state not in ("PREPARED", "COMPLETE"):
            raise ProcessorWorkerError("processing_job_state_invalid", code=6)
        return state
    return "MISSING"


def snapshot(database: Path) -> tuple[Candidate, ...]:
    """Take one deterministic read-only snapshot of currently eligible work."""
    connection = _connect_readonly(database)
    try:
        _require_authority(connection)
        try:
            rows = connection.execute(
                "SELECT a.artifact_id, a.digest_value "
                "FROM artifacts AS a "
                "JOIN capture_occurrence_assertions AS ca "
                "  ON ca.artifact_id = a.artifact_id "
                "WHERE a.artifact_kind = 'raw_media' AND a.media_type = 'video/mp4' "
                "GROUP BY a.artifact_id, a.digest_value "
                "HAVING COUNT(*) = 1 "
                "ORDER BY a.artifact_id"
            ).fetchall()
            candidates = []
            for artifact_id, digest_hex in rows:
                state = _job_state(
                    connection,
                    artifact_id=str(artifact_id),
                    digest_hex=str(digest_hex),
                )
                candidates.append(
                    Candidate(
                        artifact_id=str(artifact_id),
                        digest_hex=str(digest_hex),
                        prior_state=state,
                    )
                )
            return tuple(candidates)
        except ProcessorWorkerError:
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise ProcessorWorkerError("database_integrity_failure", code=7) from exc
    finally:
        connection.close()


def _finding_for_processing_error(code: int) -> str:
    return {
        2: "processing_invalid_argument",
        3: "processing_prerequisite_missing",
        4: "processing_identity_conflict",
        5: "processing_filesystem_failure",
        6: "processing_evidence_failure",
        7: "processing_database_failure",
    }.get(code, "processing_failure")


def _process_candidate(database: Path, spool_root: Path, candidate: Candidate) -> str:
    request = process_mod.ProcessRequest(
        database_path=str(database),
        spool_root=str(spool_root),
        input_artifact_id=candidate.artifact_id,
        profile=_PROFILE,
    )
    try:
        disposition, _plan = process_mod.process_artifact(request)
    except FinalizeError as exc:
        if exc.code == 7 and str(exc) == _LOCK_BUSY_MESSAGE:
            return "deferred"
        raise ProcessorWorkerError(_finding_for_processing_error(exc.code), exc.code) from exc
    except ProcessorWorkerError:
        raise
    except Exception as exc:
        raise ProcessorWorkerError("processing_internal_failure", code=7) from exc
    if disposition not in ("created", "existing"):
        raise ProcessorWorkerError("processing_disposition_invalid", code=6)
    return disposition


def run(database: Path, spool_root: Path) -> RunSummary:
    """Process one frozen eligibility snapshot, sequentially and fail-closed."""
    if not spool_root.is_dir():
        raise ProcessorWorkerError("spool_unavailable", code=5)

    candidates = snapshot(database)
    already_complete = 0
    prepared_resumed = 0
    newly_completed = 0
    deferred = 0

    for candidate in candidates:
        outcome = _process_candidate(database, spool_root, candidate)
        if outcome == "deferred":
            deferred = 1
            break
        if candidate.prior_state == "COMPLETE":
            already_complete += 1
        elif candidate.prior_state == "PREPARED":
            prepared_resumed += 1
        elif candidate.prior_state == "MISSING":
            newly_completed += 1
        else:
            raise ProcessorWorkerError("processing_job_state_invalid", code=6)

    completed = already_complete + prepared_resumed + newly_completed
    remaining = len(candidates) - completed
    status = "pass" if remaining == 0 else "deferred"
    return RunSummary(
        snapshot_eligible=len(candidates),
        already_complete=already_complete,
        prepared_resumed=prepared_resumed,
        newly_completed=newly_completed,
        deferred=deferred,
        remaining=remaining,
        status=status,
    )


def _exact_fields(value: object, expected: tuple[str, ...]) -> bool:
    return (
        is_dataclass(value)
        and not isinstance(value, type)
        and tuple(item.name for item in fields(value)) == expected
    )


def _entry_payload(entry: object) -> dict[str, object]:
    if not _exact_fields(entry, _EXACT_ENTRY_FIELDS):
        raise ProcessorWorkerError("approved_manifest_mismatch", code=6)
    artifact_id = getattr(entry, "artifact_id")
    deterministic_job_id = getattr(entry, "deterministic_job_id")
    digest_hex = getattr(entry, "input_digest_sha256")
    prior_state = getattr(entry, "prior_state")
    if (
        not isinstance(artifact_id, str)
        or not artifact_id.startswith("sha256:")
        or len(artifact_id) != 71
        or artifact_id != f"sha256:{digest_hex}"
        or not isinstance(digest_hex, str)
        or len(digest_hex) != 64
        or any(ch not in "0123456789abcdef" for ch in digest_hex)
        or deterministic_job_id != fingerprint.job_id_for(digest_hex, _PROFILE)
        or prior_state not in _EXACT_PRIOR_STATES
    ):
        raise ProcessorWorkerError("approved_manifest_mismatch", code=6)
    return {
        "artifact_id": artifact_id,
        "deterministic_job_id": deterministic_job_id,
        "input_digest_sha256": digest_hex,
        "prior_state": prior_state,
    }


def _validate_context(authority_context: object, approved_manifest: object) -> None:
    if (
        not _exact_fields(authority_context, _EXACT_CONTEXT_FIELDS)
        or getattr(authority_context, "schema", None) != _EXACT_CONTEXT_SCHEMA
        or getattr(authority_context, "service", None) != "processor-worker"
        or getattr(authority_context, "authority_instance", None) != _EXACT_AUTHORITY_INSTANCE
        or getattr(authority_context, "projection_schema", None) != _EXACT_MANIFEST_SCHEMA
        or getattr(authority_context, "contract_version", None) != _EXACT_CONTRACT_VERSION
        or getattr(authority_context, "database_schema_version", None)
        != _EXACT_DATABASE_SCHEMA_VERSION
        or getattr(authority_context, "proof_class", None) != _EXACT_PROOF_CLASS
    ):
        raise ProcessorWorkerError("approved_authority_context_mismatch", code=6)
    if (
        not _exact_fields(approved_manifest, _EXACT_MANIFEST_FIELDS)
        or getattr(approved_manifest, "schema", None) != _EXACT_MANIFEST_SCHEMA
        or canonical_sha256(authority_context)
        != getattr(approved_manifest, "authority_context_sha256", None)
    ):
        raise ProcessorWorkerError("approved_authority_context_mismatch", code=6)


def _reconstruct_exact_candidates(
    database: Path,
    approved_manifest: object,
    authority_context: object,
) -> tuple[Candidate, ...]:
    _validate_context(authority_context, approved_manifest)
    entries = getattr(approved_manifest, "entries", None)
    if not isinstance(entries, tuple):
        raise ProcessorWorkerError("approved_manifest_mismatch", code=6)
    payloads = tuple(_entry_payload(entry) for entry in entries)
    artifact_ids = tuple(str(item["artifact_id"]) for item in payloads)
    if artifact_ids != tuple(sorted(set(artifact_ids))):
        raise ProcessorWorkerError("approved_manifest_mismatch", code=6)

    connection = _connect_readonly(database)
    try:
        try:
            history = migration_history.recorded_history(connection)
            if (
                history != migration_history.CANONICAL_HISTORY
                or len(history) != _EXACT_DATABASE_SCHEMA_VERSION
                or getattr(authority_context, "database_schema_version")
                != len(history)
            ):
                raise ProcessorWorkerError(
                    "approved_authority_context_mismatch",
                    code=6,
                )

            current_payloads: list[dict[str, object]] = []
            candidates: list[Candidate] = []
            for approved in payloads:
                artifact_id = str(approved["artifact_id"])
                row = connection.execute(
                    "SELECT a.artifact_id, a.digest_value FROM artifacts AS a "
                    "JOIN capture_occurrence_assertions AS ca "
                    "ON ca.artifact_id = a.artifact_id "
                    "WHERE a.artifact_id = ? "
                    "AND a.artifact_kind = 'raw_media' "
                    "AND a.media_type = 'video/mp4' "
                    "GROUP BY a.artifact_id, a.digest_value "
                    "HAVING COUNT(*) = 1",
                    (artifact_id,),
                ).fetchone()
                if row is None:
                    raise ProcessorWorkerError("approved_manifest_mismatch", code=6)
                digest_hex = str(row[1])
                state = _job_state(
                    connection,
                    artifact_id=artifact_id,
                    digest_hex=digest_hex,
                )
                current = {
                    "artifact_id": artifact_id,
                    "deterministic_job_id": fingerprint.job_id_for(
                        digest_hex,
                        _PROFILE,
                    ),
                    "input_digest_sha256": digest_hex,
                    "prior_state": state,
                }
                current_payloads.append(current)
                candidates.append(Candidate(artifact_id, digest_hex, state))
            current_tuple = tuple(current_payloads)
            if current_tuple != payloads:
                raise ProcessorWorkerError("approved_manifest_mismatch", code=6)

            entries_digest = canonical_sha256(current_tuple)
            if entries_digest != getattr(
                approved_manifest,
                "entries_digest_sha256",
                None,
            ):
                raise ProcessorWorkerError("approved_manifest_mismatch", code=6)
            authority = AuthorityReference(
                service=Service.PROCESSOR,
                canonical_repository=getattr(
                    authority_context,
                    "canonical_repository",
                ),
                canonical_commit=getattr(authority_context, "canonical_commit"),
                authority_instance=getattr(
                    authority_context,
                    "authority_instance",
                ),
                projection_schema=getattr(
                    authority_context,
                    "projection_schema",
                ),
                contract_version=getattr(authority_context, "contract_version"),
                database_schema_version=getattr(
                    authority_context,
                    "database_schema_version",
                ),
                observed_snapshot_sha256=entries_digest,
                proof_class=getattr(authority_context, "proof_class"),
            )
            if authority.digest_sha256 != getattr(
                approved_manifest,
                "authority_reference_sha256",
                None,
            ):
                raise ProcessorWorkerError("approved_manifest_mismatch", code=6)
            reconstructed = {
                "schema": _EXACT_MANIFEST_SCHEMA,
                "authority_context_sha256": canonical_sha256(authority_context),
                "authority_reference_sha256": authority.digest_sha256,
                "entries_digest_sha256": entries_digest,
                "entries": current_tuple,
            }
            if canonical_sha256(reconstructed) != canonical_sha256(
                approved_manifest
            ):
                raise ProcessorWorkerError("approved_manifest_mismatch", code=6)
            return tuple(candidates)
        except ProcessorWorkerError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise ProcessorWorkerError("approved_manifest_mismatch", code=6) from exc
    finally:
        connection.close()


def run_exact(
    database: Path,
    spool_root: Path,
    approved_manifest: object,
    authority_context: object,
) -> RunSummary:
    """Process exactly one approved manifest after full pre-mutation reconstruction."""
    candidates = _reconstruct_exact_candidates(
        database,
        approved_manifest,
        authority_context,
    )
    if not spool_root.is_dir():
        raise ProcessorWorkerError("spool_unavailable", code=5)

    already_complete = 0
    prepared_resumed = 0
    newly_completed = 0
    deferred = 0
    for candidate in candidates:
        outcome = _process_candidate(database, spool_root, candidate)
        if outcome == "deferred":
            deferred = 1
            break
        if candidate.prior_state == "COMPLETE":
            already_complete += 1
        elif candidate.prior_state == "PREPARED":
            prepared_resumed += 1
        elif candidate.prior_state == "MISSING":
            newly_completed += 1
        else:
            raise ProcessorWorkerError("processing_job_state_invalid", code=6)

    completed = already_complete + prepared_resumed + newly_completed
    remaining = len(candidates) - completed
    return RunSummary(
        snapshot_eligible=len(candidates),
        already_complete=already_complete,
        prepared_resumed=prepared_resumed,
        newly_completed=newly_completed,
        deferred=deferred,
        remaining=remaining,
        status="pass" if remaining == 0 else "deferred",
    )
