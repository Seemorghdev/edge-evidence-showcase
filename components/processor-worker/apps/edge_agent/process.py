"""Effectful orchestration for ``edge-agent process-artifact``.

Turns one verified raw-media artifact into one immutable, content-addressed
``artifact-fingerprint-report.v1`` metadata artifact with one-parent lineage and
one idempotent COMPLETE processing job. Exact retries, lost responses, process
interruption, and competing local processes never duplicate committed effects;
raw evidence is never mutated.

Reuses the shared finalization, registration, and staging primitives verbatim:
  - the five-second POSIX advisory spool lock (apps.edge_agent.lock);
  - the shared raw-media evidence validator (apps.edge_agent.verification);
  - staging publish/fsync/quarantine helpers (apps.edge_agent.staging);
  - deterministic manifest assembly + serialization (apps.edge_agent.finalize);
  - the pure processor core (packages.processing.fingerprint).

Standard-library only. ``ffprobe`` is a required prerequisite (exit 3). Migration
v4 must already be applied (this command does NOT auto-migrate; exit 7 otherwise).

Exit codes (frozen): 0 created/exact-existing; 2 args/profile/identity;
3 missing ffprobe; 4 conflicting identity / no-replace collision; 5 filesystem/
publication; 6 evidence/contract/lineage/corruption; 7 migration/SQLite/
transaction/spool-lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.edge_agent import finalize, migration_history, staging, verification
from apps.edge_agent.finalize import FinalizeError
from packages.processing import fingerprint

_SQLITE_LOCK_TIMEOUT_SECONDS = 5.0
_ARTIFACT_ID_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class ProcessError(FinalizeError):
    """Effectful-layer error carrying a CLI exit code (FinalizeError subclass so
    the CLI's single ``except FinalizeError`` handler covers it)."""


@dataclass(frozen=True)
class ProcessRequest:
    database_path: str
    spool_root: str
    input_artifact_id: str
    profile: str


# ── crash barriers (production default: no-op; test-only override) ────────────
BARRIERS = (
    "after_prepared_commit",              # 1
    "during_output_partial_write",        # 2
    "after_output_partial_fsync",         # 3
    "after_output_publication",           # 4
    "after_manifest_publication",         # 5
    "after_final_db_writes_before_commit",# 6
    "after_complete_commit_before_output",# 7
)
_hooks: dict[str, Any] = {name: (lambda: None) for name in BARRIERS}


def set_barrier(name: str, callback) -> None:
    if name not in _hooks:
        raise KeyError(f"unknown crash barrier: {name}")
    _hooks[name] = callback


def reset_barriers() -> None:
    for name in BARRIERS:
        _hooks[name] = lambda: None


def barrier(name: str) -> None:
    _hooks[name]()


# ── validation ────────────────────────────────────────────────────────────────
def validate_request(request: ProcessRequest) -> None:
    if not _ARTIFACT_ID_PATTERN.match(request.input_artifact_id):
        raise ProcessError("--input-artifact-id must match ^sha256:[a-f0-9]{64}$", code=2)
    if request.profile not in fingerprint.PROFILES:
        raise ProcessError(
            f"--profile must be one of {fingerprint.PROFILES} (got {request.profile!r})",
            code=2,
        )


# ── migration + schema preflight (NO auto-migrate) ───────────────────────────
_V4_TABLES = {"processing_jobs", "artifact_lineage"}


def _require_v4(connection: sqlite3.Connection) -> None:
    present = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing = (_V4_TABLES | {"artifacts", "schema_migrations"}) - present
    if missing:
        raise ProcessError(
            f"database is not migrated to v4 (missing tables: {sorted(missing)}); "
            "run 'edge-admin db migrate' first",
            code=7,
        )
    if not migration_history.accepts_from(connection, 4):
        raise ProcessError(
            "database migration history does not match a canonical v1..v4 through v1..v8 prefix",
            code=7,
        )


# ── input evidence gate ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class InputEvidence:
    artifact_id: str
    digest_hex: str
    source_id: str
    media_type: str
    byte_size: int
    manifest_sha256: str
    finalized_at: str


def _read_input_row(connection: sqlite3.Connection, artifact_id: str) -> tuple:
    row = connection.execute(
        "SELECT artifact_kind, media_type, byte_size, digest_algorithm, digest_value, "
        "source_id, manifest_sha256, storage_uri, manifest_uri, finalized_at "
        "FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise ProcessError(f"input artifact not found in ledger: {artifact_id}", code=6)
    return row


def evidence_gate(
    connection: sqlite3.Connection, request: ProcessRequest
) -> InputEvidence:
    """Prove the verified raw input agrees across files, ledger, and contract.

    Reuses the shared raw-media validator (deterministic manifest
    bytes, recomputed media hash/size, exact raw subtype, content-addressed URI,
    canonical time, and the real FFprobe raw-media proof). Every failure here is a
    verification failure (exit 6); a missing ffprobe surfaces as exit 3.
    """
    artifact_id = request.input_artifact_id
    sha256_hex = artifact_id.split(":", 1)[1]
    spool_root = Path(request.spool_root)

    (kind, media_type, byte_size, digest_algorithm, digest_value, source_id,
     manifest_sha256, storage_uri, manifest_uri, finalized_at) = \
        _read_input_row(connection, artifact_id)

    # exact raw subtype in the ledger
    if kind != "raw_media" or media_type != "video/mp4":
        raise ProcessError("input artifact is not a raw_media video/mp4 artifact", code=6)
    if digest_algorithm != "sha256" or digest_value != sha256_hex:
        raise ProcessError("input artifact digest disagrees with its id", code=6)

    # content-addressed paths beneath the trusted spool; real regular non-symlink
    final_media = spool_root / finalize.media_relative_path(sha256_hex)
    final_manifest = spool_root / finalize.manifest_relative_path(sha256_hex)
    try:
        verification.require_within_spool(spool_root, final_media, "input media")
        verification.require_within_spool(spool_root, final_manifest, "input manifest")
    except FinalizeError as exc:
        raise ProcessError(f"input spool path check failed: {exc}", code=6) from exc
    for path, label in ((final_media, "input media"), (final_manifest, "input manifest")):
        if path.is_symlink():
            raise ProcessError(f"{label} is a symlink (refusing): {path}", code=6)
        try:
            is_file = path.is_file()
        except OSError as exc:
            raise ProcessError(f"could not check {label} {path}: {exc}", code=6) from exc
        if not is_file:
            raise ProcessError(f"{label} not found under spool: {path}", code=6)

    # storage_uri agreement (spool-relative content-addressed media URI)
    if storage_uri != finalize.storage_uri(sha256_hex):
        raise ProcessError("input storage_uri is not the content-addressed media URI", code=6)
    expected_manifest_uri = f"file:{finalize.manifest_relative_path(sha256_hex)}"
    if manifest_uri != expected_manifest_uri:
        raise ProcessError("input manifest_uri is not the content-addressed manifest URI", code=6)

    # deterministic manifest bytes + hash equals the ledger manifest_sha256
    try:
        manifest_bytes = final_manifest.read_bytes()
    except OSError as exc:
        raise ProcessError(f"could not read input manifest: {exc}", code=6) from exc
    # Derive the already-proven interval start from the immutable manifest end so
    # the exact shared SPEC-003/004 validator can be reused. This invents no new
    # occurrence authority: it merely supplies the validator's locked ten-second
    # arithmetic for an artifact whose registration already proved that interval.
    try:
        candidate = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProcessError(f"input manifest is not valid UTF-8 JSON: {exc}", code=6) from exc
    try:
        from datetime import timedelta
        end = finalize.validate_rfc3339_utc(candidate["finalized_at"], "manifest finalized_at")
        start = end - timedelta(seconds=finalize.EXPECTED_DURATION_SECONDS)
        capture_started_at = start.isoformat().replace("+00:00", "Z")
        manifest, media_hash, media_size, recomputed_manifest_sha = (
            verification.verify_media_and_manifest(
                sha256_hex=sha256_hex,
                media_path=final_media,
                manifest_bytes=manifest_bytes,
                capture_started_at=capture_started_at,
            )
        )
    except (KeyError, TypeError) as exc:
        raise ProcessError(f"input manifest lacks a valid finalized_at: {exc}", code=6) from exc
    except FinalizeError as exc:
        raise ProcessError(str(exc), code=exc.code) from exc

    if recomputed_manifest_sha != manifest_sha256:
        raise ProcessError("input manifest hash disagrees with the ledger manifest_sha256", code=6)

    # The shared validator proved bytes, raw subtype, URI, interval, and ffprobe.
    # Complete the database-row agreement checks that are outside its boundary.
    if manifest["byte_size"] != media_size or byte_size != media_size:
        raise ProcessError("input byte_size disagrees across manifest/ledger/media", code=6)
    if manifest["source_id"] != source_id:
        raise ProcessError("input manifest source_id disagrees with ledger", code=6)
    if manifest["finalized_at"] != finalized_at:
        raise ProcessError("input manifest finalized_at disagrees with ledger", code=6)

    return InputEvidence(
        artifact_id=artifact_id,
        digest_hex=sha256_hex,
        source_id=source_id,
        media_type="video/mp4",
        byte_size=media_size,
        manifest_sha256=manifest_sha256,
        finalized_at=manifest["finalized_at"],
    )


# ── derived report + manifest planning (pure given evidence) ─────────────────
@dataclass(frozen=True)
class DerivedPlan:
    job_id: str
    parameters_json: bytes
    parameters_sha256: str
    report_bytes: bytes
    derived_digest_hex: str
    derived_artifact_id: str
    manifest_bytes: bytes
    manifest_sha256: str


def plan_derivation(evidence: InputEvidence, profile: str) -> DerivedPlan:
    """Derive the job id, canonical parameters, report bytes, derived identity,
    and derived manifest. Pure given the verified input evidence."""
    params_json = fingerprint.canonical_parameters(profile)
    params_sha = fingerprint.parameters_sha256(profile)
    job_id = fingerprint.job_id_for(evidence.digest_hex, profile)

    if profile == "identity":
        report = fingerprint.build_report(
            profile="identity",
            artifact_id=evidence.artifact_id,
            manifest_sha256=evidence.manifest_sha256,
        )
    else:
        report = fingerprint.build_report(
            profile="integrity",
            artifact_id=evidence.artifact_id,
            manifest_sha256=evidence.manifest_sha256,
            source_assertion=evidence.source_id,
            media_type=evidence.media_type,
            byte_size=evidence.byte_size,
            digest_value=evidence.digest_hex,
        )
    report_bytes = fingerprint.serialize_report(report)
    derived_hex = fingerprint.derived_identity(report_bytes)

    # Derived manifest reuses artifact-manifest.v1 for a metadata artifact.
    manifest = _build_derived_manifest(
        source_id=evidence.source_id,
        derived_hex=derived_hex,
        byte_size=len(report_bytes),
        finalized_at=evidence.finalized_at,      # inherited logical evidence time
        parent_artifact_id=evidence.artifact_id,
    )
    manifest_bytes = finalize.serialize_manifest(manifest)
    return DerivedPlan(
        job_id=job_id,
        parameters_json=params_json,
        parameters_sha256=params_sha,
        report_bytes=report_bytes,
        derived_digest_hex=derived_hex,
        derived_artifact_id=f"sha256:{derived_hex}",
        manifest_bytes=manifest_bytes,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _build_derived_manifest(
    *, source_id: str, derived_hex: str, byte_size: int, finalized_at: str,
    parent_artifact_id: str,
) -> dict[str, Any]:
    """Assemble the frozen artifact-manifest.v1 mapping for the metadata artifact.

    Uses the derived vendor media type and the metadata kind, describes the exact
    report bytes, sets parent_artifact_id to the raw input, and inherits
    finalized_at as the logical evidence time. Validated against the frozen shape.
    """
    manifest = {
        "schema_version": finalize.MANIFEST_SCHEMA_VERSION,
        "artifact_id": f"sha256:{derived_hex}",
        "source_id": source_id,
        "artifact_kind": fingerprint.ARTIFACT_KIND,           # metadata
        "media_type": fingerprint.MEDIA_TYPE,                 # frozen vendor JSON type
        "byte_size": byte_size,
        "digest": {"algorithm": "sha256", "value": derived_hex},
        "storage_uri": _complete_storage_uri(derived_hex),
        "finalized_at": finalized_at,
        "parent_artifact_id": parent_artifact_id,
    }
    finalize.validate_manifest_shape(manifest)              # exact frozen shape, exit 6
    return manifest


# ── content-addressed derived paths (report under complete/, manifest under manifests/) ─
def _complete_relative_path(derived_hex: str) -> str:
    return f"complete/sha256/{derived_hex[:2]}/{derived_hex}.json"


def _manifest_relative_path(derived_hex: str) -> str:
    return f"manifests/sha256/{derived_hex[:2]}/{derived_hex}.json"


def _complete_storage_uri(derived_hex: str) -> str:
    return f"file:{_complete_relative_path(derived_hex)}"


def _partial_dir(spool_root: Path, job_id: str) -> Path:
    return spool_root / "partial" / "processing" / job_id


def _quarantine_dir(spool_root: Path, job_id: str) -> Path:
    return spool_root / "quarantine" / "processing" / job_id


# ── SQLite job authority (adopt-or-compare; PREPARED then COMPLETE) ───────────
def _connect(database: Path) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(database, timeout=_SQLITE_LOCK_TIMEOUT_SECONDS)
    except sqlite3.Error as exc:
        raise ProcessError(f"could not open database {database}: {exc}", code=7) from exc
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute(f"PRAGMA busy_timeout = {int(_SQLITE_LOCK_TIMEOUT_SECONDS * 1000)}")
    return conn


def _read_job(conn: sqlite3.Connection, job_id: str) -> tuple | None:
    return conn.execute(
        "SELECT input_artifact_id, processor_name, processor_version, output_contract, "
        "parameters_json, parameters_sha256, state, output_artifact_id "
        "FROM processing_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()


def _job_identity_tuple(plan: DerivedPlan, evidence: InputEvidence) -> tuple:
    return (
        evidence.artifact_id, fingerprint.PROCESSOR_NAME, fingerprint.PROCESSOR_VERSION,
        fingerprint.OUTPUT_CONTRACT, plan.parameters_json.decode("utf-8"), plan.parameters_sha256,
    )


def _create_or_adopt_prepared(conn: sqlite3.Connection, plan: DerivedPlan,
                              evidence: InputEvidence) -> str:
    """Create the PREPARED job, or adopt an exact existing one. Its own transaction.

    A row with the same job_id but different identity fields is a conflict (exit 4).
    A COMPLETE row is handled by the caller before this point. Returns the state
    string ('created' or 'existing')."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _read_job(conn, plan.job_id)
        if row is not None:
            identity = tuple(row[:6])
            if identity != _job_identity_tuple(plan, evidence):
                conn.rollback()
                raise ProcessError(
                    "processing job id already present with different identity; conflict",
                    code=4,
                )
            conn.rollback()
            return "existing"
        conn.execute(
            "INSERT INTO processing_jobs (job_id, input_artifact_id, processor_name, "
            "processor_version, output_contract, parameters_json, parameters_sha256, state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'PREPARED')",
            (plan.job_id, evidence.artifact_id, fingerprint.PROCESSOR_NAME,
             fingerprint.PROCESSOR_VERSION, fingerprint.OUTPUT_CONTRACT,
             plan.parameters_json.decode("utf-8"), plan.parameters_sha256),
        )
        conn.commit()
        return "created"
    except ProcessError:
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        # UNIQUE(input, processor, version, contract, params) collision under a
        # different job_id would be an identity contradiction.
        raise ProcessError(f"processing job uniqueness conflict: {exc}", code=4) from exc
    except sqlite3.Error as exc:
        conn.rollback()
        raise ProcessError(f"PREPARED job commit failed: {exc}", code=7) from exc


def _finalize_complete(conn: sqlite3.Connection, plan: DerivedPlan,
                       evidence: InputEvidence) -> tuple[str, str, str]:
    """One transaction: insert/adopt derived artifact + lineage, PREPARED→COMPLETE.

    Adopt-or-compare per row so an exact rerun after a lost response is a no-op.
    Returns (artifact_state, lineage_state, job_state) dispositions."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        artifact_state = _upsert_derived_artifact(conn, plan, evidence)
        lineage_state = _upsert_lineage(conn, plan, evidence)
        job_state = _transition_job_complete(conn, plan)
        barrier("after_final_db_writes_before_commit")   # 6
        conn.commit()
        barrier("after_complete_commit_before_output")   # 7
        return artifact_state, lineage_state, job_state
    except ProcessError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ProcessError(f"COMPLETE transaction violates a constraint: {exc}", code=6) from exc
    except sqlite3.OperationalError as exc:
        conn.rollback()
        raise ProcessError(f"database locked or unavailable: {exc}", code=7) from exc
    except sqlite3.Error as exc:
        conn.rollback()
        raise ProcessError(f"COMPLETE transaction failed: {exc}", code=7) from exc


def _upsert_derived_artifact(conn: sqlite3.Connection, plan: DerivedPlan,
                             evidence: InputEvidence) -> str:
    expected = (
        evidence.source_id, fingerprint.ARTIFACT_KIND, fingerprint.MEDIA_TYPE,
        len(plan.report_bytes), "sha256", plan.derived_digest_hex,
        _complete_storage_uri(plan.derived_digest_hex),
        f"file:{_manifest_relative_path(plan.derived_digest_hex)}",
        plan.manifest_sha256, evidence.finalized_at,
    )
    row = conn.execute(
        "SELECT source_id, artifact_kind, media_type, byte_size, digest_algorithm, "
        "digest_value, storage_uri, manifest_uri, manifest_sha256, finalized_at "
        "FROM artifacts WHERE artifact_id = ?",
        (plan.derived_artifact_id,),
    ).fetchone()
    if row is not None:
        if tuple(row) != expected:
            raise ProcessError(
                "derived artifact already present with different immutable fields; conflict",
                code=4,
            )
        return "existing"
    conn.execute(
        "INSERT INTO artifacts (artifact_id, source_id, artifact_kind, media_type, "
        "byte_size, digest_algorithm, digest_value, storage_uri, manifest_uri, "
        "manifest_sha256, finalized_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (plan.derived_artifact_id, *expected),
    )
    return "created"


def _upsert_lineage(conn: sqlite3.Connection, plan: DerivedPlan,
                    evidence: InputEvidence) -> str:
    row = conn.execute(
        "SELECT parent_artifact_id, relation_type FROM artifact_lineage "
        "WHERE child_artifact_id = ?",
        (plan.derived_artifact_id,),
    ).fetchone()
    if row is not None:
        if tuple(row) != (evidence.artifact_id, fingerprint.RELATION_TYPE):
            raise ProcessError(
                "derived artifact already has a different parent lineage; conflict", code=4
            )
        return "existing"
    conn.execute(
        "INSERT INTO artifact_lineage (child_artifact_id, parent_artifact_id, relation_type) "
        "VALUES (?, ?, ?)",
        (plan.derived_artifact_id, evidence.artifact_id, fingerprint.RELATION_TYPE),
    )
    return "created"


def _transition_job_complete(conn: sqlite3.Connection, plan: DerivedPlan) -> str:
    row = _read_job(conn, plan.job_id)
    if row is None:
        raise ProcessError("PREPARED job vanished before completion; corruption", code=6)
    state, output_artifact_id = row[6], row[7]
    if state == "COMPLETE":
        if output_artifact_id != plan.derived_artifact_id:
            raise ProcessError(
                "COMPLETE job references a different output artifact; corruption", code=6
            )
        return "existing"
    # PREPARED → COMPLETE (trigger enforces matching lineage already inserted above)
    conn.execute(
        "UPDATE processing_jobs SET state = 'COMPLETE', output_artifact_id = ?, "
        "completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ?",
        (plan.derived_artifact_id, plan.job_id),
    )
    return "created"


def _require_unambiguous_input_assertion(conn: sqlite3.Connection,
                                         input_artifact_id: str) -> None:
    """Processing eligibility: the raw input artifact must have exactly one COMPLETE
    capture assertion before a new (or resumed) processing job may mutate anything.

    Reads ``capture_occurrence_assertions`` for the input artifact. Both error
    messages are path-neutral: no artifact id, occurrence id, URI, count, or path is
    appended. Read-only; raises before any mutation.
    """
    count = conn.execute(
        "SELECT count(*) FROM capture_occurrence_assertions WHERE artifact_id = ?",
        (input_artifact_id,),
    ).fetchone()[0]
    if count == 0:
        raise ProcessError("input artifact has no COMPLETE capture assertion", code=6)
    if count > 1:
        raise ProcessError(
            "input artifact has multiple COMPLETE capture assertions; "
            "occurrence selection is required",
            code=4,
        )


# ── the main orchestration (frozen 12-step order) ────────────────────────────
def process_artifact(request: ProcessRequest) -> tuple[str, "DerivedPlan"]:
    """Execute the bounded deterministic slice. Returns (disposition, plan).

    disposition is 'created' (a new COMPLETE result was produced) or 'existing'
    (an exact prior COMPLETE result was adopted). Raises ProcessError with the
    frozen exit code on any failure.
    """
    validate_request(request)                                  # 1a (args)
    spool_root = Path(request.spool_root)
    database = Path(request.database_path)

    if not spool_root.is_dir():
        raise ProcessError(f"spool root is not a directory: {spool_root}", code=5)

    # Lock covers the WHOLE flow so a competing local process cannot race the gate,
    # the publication, or the job transaction (the existing 5 s advisory spool lock).
    from apps.edge_agent import lock as spool_lock_mod
    with spool_lock_mod.spool_lock(spool_root, mode="exclusive"):            # 2 (exit 7 on timeout)
        conn = _connect(database)
        try:
            _require_v4(conn)                              # 1a (v4; exit 7)
            evidence = evidence_gate(conn, request)        # 1b (input evidence; exit 6/3)
            plan = plan_derivation(evidence, request.profile)  # 3 (canonical params + job id)

            # Fast path: an exact prior COMPLETE job → verified adoption, no rewrite.
            existing = _read_job(conn, plan.job_id)
            if existing is not None and existing[6] == "COMPLETE":
                _verify_authority(conn, spool_root, plan, evidence)
                return "existing", plan

            # SPEC-011 eligibility gate: BEFORE any filesystem or database mutation
            # (and only AFTER resolving an existing COMPLETE job above, so an exact
            # rerun stays valid even when later occurrences added more assertions),
            # count the COMPLETE capture assertions for the raw input artifact.
            #   zero  → exit 6, no unambiguous input evidence exists yet;
            #   many  → exit 4, occurrence selection is required (deferred to a later
            #           processing-provenance spec);
            #   one   → proceed with that unambiguous assertion as the input evidence.
            # Both messages are path-neutral (no artifact id, occurrence id, URI,
            # count, or filesystem path appended). Applies to both identity and
            # integrity profiles.
            _require_unambiguous_input_assertion(conn, request.input_artifact_id)

            # Before durable PREPARED authority exists, prove every deterministic
            # path this run may write (including quarantine for stale partials).
            _preflight_processing_paths(spool_root, plan)

            # 4. create/adopt exact PREPARED (its own committed transaction).
            _create_or_adopt_prepared(conn, plan, evidence)
            barrier("after_prepared_commit")               # 1

            # 5-10. produce + publish the report and derived manifest (report first,
            #        manifest last), with rerun/quarantine recovery.
            _produce_and_publish(spool_root, plan)
            _verify_final_pair(spool_root, plan, evidence)

            # 11. one COMPLETE transaction (artifact + lineage + PREPARED→COMPLETE).
            _finalize_complete(conn, plan, evidence)

            # 12. re-read authority; the disposition is 'created'.
            _verify_authority(conn, spool_root, plan, evidence)
            return "created", plan
        finally:
            conn.close()


def _verify_authority(conn: sqlite3.Connection, spool_root: Path, plan: "DerivedPlan",
                      evidence: InputEvidence) -> None:
    """Re-read files + rows and assert full agreement; never repair by guesswork."""
    _verify_final_pair(spool_root, plan, evidence)
    job = _read_job(conn, plan.job_id)
    if job is None or job[6] != "COMPLETE" or job[7] != plan.derived_artifact_id:
        raise ProcessError("processing job authority disagrees with files; corruption", code=6)
    artifact = conn.execute(
        "SELECT source_id, artifact_kind, media_type, byte_size, digest_algorithm, "
        "digest_value, storage_uri, manifest_uri, manifest_sha256, finalized_at "
        "FROM artifacts WHERE artifact_id = ?",
        (plan.derived_artifact_id,),
    ).fetchone()
    expected_artifact = (
        evidence.source_id, fingerprint.ARTIFACT_KIND, fingerprint.MEDIA_TYPE,
        len(plan.report_bytes), "sha256", plan.derived_digest_hex,
        _complete_storage_uri(plan.derived_digest_hex),
        f"file:{_manifest_relative_path(plan.derived_digest_hex)}",
        plan.manifest_sha256, evidence.finalized_at,
    )
    if artifact is None or tuple(artifact) != expected_artifact:
        raise ProcessError("derived artifact authority disagrees with files; corruption", code=6)
    lineage = conn.execute(
        "SELECT parent_artifact_id, relation_type FROM artifact_lineage WHERE child_artifact_id = ?",
        (plan.derived_artifact_id,),
    ).fetchone()
    if lineage is None or tuple(lineage) != (evidence.artifact_id, fingerprint.RELATION_TYPE):
        raise ProcessError("lineage authority disagrees; corruption", code=6)


def _verify_final_pair(spool_root: Path, plan: "DerivedPlan",
                       evidence: InputEvidence) -> None:
    """Verify the fully published deterministic pair before and after authority.

    The pre-commit call prevents COMPLETE authority for altered publication; the
    post-commit call remains a defense against later filesystem disagreement.
    """
    final_report = spool_root / _complete_relative_path(plan.derived_digest_hex)
    final_manifest = spool_root / _manifest_relative_path(plan.derived_digest_hex)
    for path, label in ((final_report, "derived report"),
                        (final_manifest, "derived manifest")):
        _guard_process_path(spool_root, path, label)
        if not path.is_file():
            raise ProcessError(f"COMPLETE {label} is not a regular file; corruption", code=6)
    try:
        report_bytes = final_report.read_bytes()
        manifest_bytes = final_manifest.read_bytes()
    except OSError as exc:
        raise ProcessError(f"COMPLETE result missing on disk; corruption: {exc}", code=6) from exc
    if report_bytes != plan.report_bytes:
        raise ProcessError("published report bytes differ from the deterministic report; corruption", code=6)
    if manifest_bytes != plan.manifest_bytes:
        raise ProcessError("published manifest bytes differ from the deterministic manifest; corruption", code=6)
    if hashlib.sha256(report_bytes).hexdigest() != plan.derived_digest_hex:
        raise ProcessError("published report hash disagrees with derived identity", code=6)
    if hashlib.sha256(manifest_bytes).hexdigest() != plan.manifest_sha256:
        raise ProcessError("published manifest hash disagrees with planned manifest hash", code=6)
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProcessError(f"published derived manifest is not valid UTF-8 JSON: {exc}", code=6) from exc
    try:
        finalize.validate_manifest_shape(manifest)
    except FinalizeError as exc:
        raise ProcessError(str(exc), code=6) from exc
    if manifest_bytes != finalize.serialize_manifest(manifest):
        raise ProcessError("published derived manifest is not deterministic", code=6)
    expected = {
        "artifact_id": plan.derived_artifact_id,
        "source_id": evidence.source_id,
        "artifact_kind": fingerprint.ARTIFACT_KIND,
        "media_type": fingerprint.MEDIA_TYPE,
        "byte_size": len(report_bytes),
        "storage_uri": _complete_storage_uri(plan.derived_digest_hex),
        "finalized_at": evidence.finalized_at,
        "parent_artifact_id": evidence.artifact_id,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ProcessError("published derived manifest facts disagree with the plan", code=6)
    if manifest.get("digest") != {"algorithm": "sha256", "value": plan.derived_digest_hex}:
        raise ProcessError("published derived manifest digest disagrees with report", code=6)


def _produce_and_publish(spool_root: Path, plan: "DerivedPlan") -> None:
    """Steps 5-10: partials → fsync/verify → publish report first, manifest last.

    Reuses the shared staging primitives (exclusive-create partials, atomic
    no-replace publish, directory fsync). Rerun recovery: a valid existing final
    pair is adopted after full byte checks; an invalid/incomplete partial is
    quarantined (by partial-byte SHA-256) before regeneration.
    """
    final_report = spool_root / _complete_relative_path(plan.derived_digest_hex)
    final_manifest = spool_root / _manifest_relative_path(plan.derived_digest_hex)
    part_dir = _partial_dir(spool_root, plan.job_id)
    output_partial = part_dir / "output.json.partial"
    manifest_partial = part_dir / "manifest.json.partial"
    for path, label in (
        (final_report, "derived report"),
        (final_manifest, "derived manifest"),
        (output_partial, "derived report partial"),
        (manifest_partial, "derived manifest partial"),
    ):
        _guard_process_path(spool_root, path, label)

    # Adopt a byte-exact report already published by an interrupted run. A valid
    # report without its manifest is a permitted report-first recovery state.
    report_is_final = final_report.is_file()
    if report_is_final and final_report.read_bytes() != plan.report_bytes:
        raise ProcessError("wrong object at content-addressed derived report path", code=6)
    if final_manifest.is_file() and final_manifest.read_bytes() != plan.manifest_bytes:
        raise ProcessError("wrong object at content-addressed derived manifest path", code=6)
    if report_is_final and final_manifest.is_file():
        return
    # Final manifest without content is corruption (no mutation).
    if final_manifest.is_file() and not final_report.is_file():
        raise ProcessError("final derived manifest without report; corruption", code=6)

    try:
        part_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProcessError(f"could not create processing partial dir: {exc}", code=5) from exc
    staging._prove_same_filesystem(spool_root, output_partial, "output partial")

    if not report_is_final:
        _stage_partial(spool_root, output_partial, plan.report_bytes, plan.job_id,
                       kind="output", mid_barrier="during_output_partial_write")
        barrier("after_output_partial_fsync")              # 3
    _stage_partial(spool_root, manifest_partial, plan.manifest_bytes, plan.job_id,
                   kind="manifest", mid_barrier=None)

    # Publish report first (valid final report without manifest is the permitted
    # media-first failure state that a rerun resolves by publishing the manifest).
    if not report_is_final:
        try:
            staging.publish_no_replace(output_partial, final_report, "derived report", spool_root)
        except staging._PublishCollision:
            staging.verify_manifest_bytes(final_report, plan.report_bytes)  # byte-exact adopt
            staging._remove_and_fsync_partial(output_partial)
        barrier("after_output_publication")                # 4
    try:
        staging.publish_no_replace(manifest_partial, final_manifest, "derived manifest", spool_root)
    except staging._PublishCollision:
        staging.verify_manifest_bytes(final_manifest, plan.manifest_bytes)
        staging._remove_and_fsync_partial(manifest_partial)
    barrier("after_manifest_publication")                  # 5


def _guard_process_path(spool_root: Path, target: Path, label: str) -> None:
    """Apply the shared within-spool, leaf, and ancestor symlink protections."""
    try:
        staging._guard_within_spool(spool_root, target, label)
        staging._reject_symlinked_ancestors(spool_root, target, label)
        staging._prove_same_filesystem(spool_root, target, label)
    except FinalizeError as exc:
        raise ProcessError(f"{label} path is unsafe: {exc}", code=exc.code) from exc


def _preflight_processing_paths(spool_root: Path, plan: "DerivedPlan") -> None:
    """Read-only path audit under the spool lock, before PREPARED insertion."""
    part_dir = _partial_dir(spool_root, plan.job_id)
    candidates = (
        (spool_root / _complete_relative_path(plan.derived_digest_hex),
         "derived report", None, None),
        (spool_root / _manifest_relative_path(plan.derived_digest_hex),
         "derived manifest", None, None),
        (part_dir / "output.json.partial", "derived report partial",
         plan.report_bytes, "output"),
        (part_dir / "manifest.json.partial", "derived manifest partial",
         plan.manifest_bytes, "manifest"),
    )
    for path, label, expected, kind in candidates:
        _guard_process_path(spool_root, path, label)
        if expected is None or not path.exists():
            continue
        if not path.is_file():
            raise ProcessError(f"{label} is not a regular file", code=5)
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise ProcessError(f"could not read {label}: {exc}", code=5) from exc
        if existing != expected:
            qhash = hashlib.sha256(existing).hexdigest()
            qdest = _quarantine_dir(spool_root, plan.job_id) / \
                f"{qhash}.{kind}.json.partial"
            _guard_process_path(spool_root, qdest, f"quarantine {label}")


def _stage_partial(spool_root: Path, partial: Path, payload: bytes, job_id: str,
                   *, kind: str, mid_barrier: str | None) -> None:
    """Exclusively create a partial with the exact payload; quarantine a stale one.

    A partial left by a prior interrupted run is quarantined by its byte SHA-256
    before regeneration (identical existing quarantine content is adopted; differing
    bytes at the same hash path are corruption)."""
    if partial.exists() or partial.is_symlink():
        if not partial.is_file() or partial.is_symlink():
            raise ProcessError(f"processing partial is not a regular file: {partial}", code=5)
        existing = partial.read_bytes()
        if existing == payload:
            return
        qhash = hashlib.sha256(existing).hexdigest()
        qdest = _quarantine_dir(spool_root, job_id) / f"{qhash}.{kind}.json.partial"
        staging.quarantine_partial(partial, qdest, f"{kind} partial", spool_root)
    if mid_barrier is not None:
        _write_partial_with_barrier(partial, payload, mid_barrier)
    else:
        staging.write_manifest_partial(partial, payload)


def _write_partial_with_barrier(partial: Path, payload: bytes, mid_barrier: str) -> None:
    """Exclusive-create + write + fsync a partial, firing a barrier mid-write."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(partial, flags, 0o644)
    except FileExistsError as exc:
        raise ProcessError(f"processing partial already exists: {partial}", code=4) from exc
    except OSError as exc:
        raise ProcessError(f"could not create processing partial {partial}: {exc}", code=5) from exc
    try:
        with os.fdopen(fd, "wb") as out:
            half = max(1, len(payload) // 2)
            out.write(payload[:half])
            out.flush()
            os.fsync(out.fileno())
            barrier(mid_barrier)                           # 2 (test-only SIGKILL point)
            out.write(payload[half:])
            out.flush()
            os.fsync(out.fileno())
    except OSError as exc:
        raise ProcessError(f"processing partial write failed: {exc}", code=5) from exc


# ── CLI disposition line ──────────────────────────────────────────────────────
def disposition_line(disposition: str, plan: "DerivedPlan") -> str:
    return (
        f"result={disposition} "
        f"job_id={plan.job_id} "
        f"artifact={plan.derived_artifact_id} "
        f"report={_complete_relative_path(plan.derived_digest_hex)} "
        f"manifest={_manifest_relative_path(plan.derived_digest_hex)}"
    )


# ── SPEC-008 public extraction ───────────────────────────────────────────────
# A small, stable public surface over the SPEC-007 derived-path and final-pair
# proof so the read-only SPEC-008 verifier reuses the exact same logic instead of
# a divergent copy. These are thin, behavior-preserving aliases of the internals
# above; they add NO new behavior and perform no database or spool writes.
def complete_relative_path(derived_hex: str) -> str:
    """Spool-relative content-addressed path of a derived report's bytes."""
    return _complete_relative_path(derived_hex)


def manifest_relative_path(derived_hex: str) -> str:
    """Spool-relative content-addressed path of a derived manifest."""
    return _manifest_relative_path(derived_hex)


def complete_storage_uri(derived_hex: str) -> str:
    """The ``file:`` storage URI a derived metadata artifact must declare."""
    return _complete_storage_uri(derived_hex)


def guard_process_path(spool_root: Path, target: Path, label: str) -> None:
    """Within-spool + leaf/ancestor-symlink + same-filesystem safety for a derived
    path. Raises ProcessError (code 5 unsafe root/filesystem, code 4 symlink)."""
    _guard_process_path(spool_root, target, label)


def verify_final_pair(spool_root: Path, plan: "DerivedPlan",
                      evidence: InputEvidence) -> None:
    """Re-read + fully verify the published derived (report, manifest) pair against
    the reconstructed plan. Raises ProcessError(code=6) on any disagreement. This is
    the exact final-pair proof; it never writes."""
    _verify_final_pair(spool_root, plan, evidence)
