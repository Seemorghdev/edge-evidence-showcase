"""Provider-neutral bounded replication convergence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packages.agent_contracts.canonical import canonical_sha256
from packages.replication.contracts.model import ReplicationError, validate_target_id
from packages.replication.contracts.target import ReplicationTarget
from packages.replication.contracts.target import ReplicationTargetFactory
from packages.replication.action.implementation_identity import (
    CANONICAL_REPOSITORY_ID,
    reconstruct_implementation_identity,
)
from packages.replication.action.manifest import (
    CandidateManifest,
    ReplicationAuthorityContext,
    build_authority_context,
    build_candidate_manifest,
)
from packages.replication.action.projections import (
    ReplicaRowAbsenceProjection,
    ReplicaRowProjection,
    TargetSnapshotProjection,
    project_authority_snapshot,
    project_remaining_work,
    project_source_eligibility,
    read_replica_witness,
    revalidate_source_entry,
)

from . import authority
from .source import local_size_and_hash


@dataclass(frozen=True)
class RunSummary:
    discovered: int = 0
    inserted: int = 0
    published: int = 0
    adopted: int = 0
    verified: int = 0
    partials_cleaned: int = 0

    def public(self) -> dict[str, int | str]:
        return {
            "status": "pass",
            "discovered": self.discovered,
            "inserted": self.inserted,
            "published": self.published,
            "adopted": self.adopted,
            "verified": self.verified,
            "partials_cleaned": self.partials_cleaned,
        }


def _load_target(connection, target_id: str, target: ReplicationTarget) -> str:
    authority.require_current(connection)
    row = authority.target_row(connection, target_id)
    if row is None:
        raise ReplicationError("target_identity_mismatch", code=4)
    adapter_kind, marker_sha256 = row
    if adapter_kind != target.adapter_kind:
        raise ReplicationError("target_identity_mismatch", code=4)
    return marker_sha256


def init_target(database: Path, target: ReplicationTarget, target_id: str) -> RunSummary:
    validate_target_id(target_id)
    connection = authority.connect(database)
    try:
        authority.require_current(connection)
        existing = authority.target_row(connection, target_id)
        if existing is not None:
            adapter_kind, marker_sha256 = existing
            if adapter_kind != target.adapter_kind:
                raise ReplicationError("target_identity_mismatch", code=4)
            target.bind(target_id, marker_sha256)
            return RunSummary()

        marker_sha256 = target.initialize(target_id)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = authority.target_row(connection, target_id)
            if row is None:
                authority.insert_target(
                    connection,
                    target_id,
                    target.adapter_kind,
                    marker_sha256,
                )
            elif row != (target.adapter_kind, marker_sha256):
                raise ReplicationError("target_identity_mismatch", code=4)
            connection.commit()
        except ReplicationError:
            connection.rollback()
            raise
        except Exception as exc:
            connection.rollback()
            raise ReplicationError("database_integrity_failure", code=7) from exc
        target.bind(target_id, marker_sha256)
        return RunSummary()
    finally:
        connection.close()


def reconcile(
    database: Path,
    spool_root: Path,
    target: ReplicationTarget,
    target_id: str,
) -> RunSummary:
    """Converge only already-known PENDING work through neutral target semantics."""

    del spool_root
    validate_target_id(target_id)
    connection = authority.connect(database)
    cleaned = 0
    adopted = 0
    try:
        marker_sha256 = _load_target(connection, target_id, target)
        bound = target.bind(target_id, marker_sha256)
        for obj in authority.pending_objects(connection, target_id):
            bound.validate_identity()
            if bound.cleanup_transient(obj):
                cleaned += 1
            state = bound.inspect(obj)
            if state == "exact":
                bound.validate_identity()
                authority.mark_verified(connection, obj)
                adopted += 1
        return RunSummary(adopted=adopted, verified=adopted, partials_cleaned=cleaned)
    finally:
        connection.close()


def run(
    database: Path,
    spool_root: Path,
    target: ReplicationTarget,
    target_id: str,
) -> RunSummary:
    validate_target_id(target_id)
    reconciled = reconcile(database, spool_root, target, target_id)
    connection = authority.connect(database)
    published = 0
    adopted = 0
    try:
        marker_sha256 = _load_target(connection, target_id, target)
        bound = target.bind(target_id, marker_sha256)
        objects = authority.discover(database, spool_root, target_id)
        inserted = authority.register_discovered(connection, target_id, objects)
        for obj in authority.pending_objects(connection, target_id):
            bound.validate_identity()
            authority.record_attempt(connection, obj)
            try:
                source_size, source_digest = local_size_and_hash(spool_root, obj.relative_uri)
                if source_size != obj.expected_byte_size or source_digest != obj.expected_sha256:
                    raise ReplicationError("local_source_corrupt", code=6)
                result = bound.publish_immutable(spool_root, obj)
            except ReplicationError as exc:
                authority.record_failure(connection, obj, exc.finding)
                raise
            authority.mark_verified(connection, obj)
            if result == "published":
                published += 1
            else:
                adopted += 1
        return RunSummary(
            discovered=len(objects),
            inserted=inserted,
            published=published,
            adopted=adopted + reconciled.adopted,
            verified=published + adopted + reconciled.verified,
            partials_cleaned=reconciled.partials_cleaned,
        )
    finally:
        connection.close()


def verify(database: Path, target: ReplicationTarget, target_id: str) -> RunSummary:
    validate_target_id(target_id)
    connection = authority.connect(database, readonly=True)
    try:
        marker_sha256 = _load_target(connection, target_id, target)
        bound = target.bind(target_id, marker_sha256)
        objects = authority.verified_objects(connection, target_id)
        for obj in objects:
            bound.validate_identity()
            bound.verify(obj)
        bound.validate_identity()
        return RunSummary(verified=len(objects))
    finally:
        connection.close()


@dataclass(frozen=True)
class ExactEntryResult:
    ordinal: int
    result_code: str
    replica_row_sha256: str | None
    destination_inspection_sha256: str | None
    finding_code: str | None


@dataclass(frozen=True)
class ExactRunResult:
    schema = "replication-run-exact-result.v1"

    status: str
    implementation_identity_sha256: str
    authority_context_sha256: str
    candidate_manifest_sha256: str
    runtime_target_identity_sha256: str
    entry_results: tuple[ExactEntryResult, ...]
    entry_results_sha256: str
    candidate_count: int
    processed_count: int
    published_count: int
    adopted_count: int
    verified_count: int
    failed_ordinal: int | None
    finding_code: str | None


def run_exact(
    database: Path,
    spool_root: Path,
    target_factory: ReplicationTargetFactory,
    authority_context: ReplicationAuthorityContext,
    approved_manifest: CandidateManifest,
) -> ExactRunResult:
    """Execute exactly one frozen manifest and stop on the first failed entry."""

    repository_root = Path(__file__).resolve().parents[3]
    identity = reconstruct_implementation_identity(
        repository_root,
        authority_context.canonical_commit,
        trusted_repository_id=CANONICAL_REPOSITORY_ID,
    )
    if identity.sha256 != authority_context.implementation_identity_sha256:
        raise ReplicationError("implementation_drift", code=7)
    if approved_manifest.implementation_identity_sha256 != identity.sha256:
        raise ReplicationError("candidate_manifest_changed", code=7)
    if approved_manifest.authority_context_sha256 != authority_context.sha256:
        raise ReplicationError("authority_context_changed", code=7)
    composition = target_factory.composition
    if composition.sha256 != approved_manifest.target_composition_sha256:
        raise ReplicationError("target_composition_changed", code=7)

    source = project_source_eligibility(database, spool_root, composition.target_id)
    authority_snapshot = project_authority_snapshot(database, target_factory.composition.target_id)
    if authority_snapshot.target_row.sha256 != approved_manifest.target_row_sha256:
        raise ReplicationError("target_row_changed", code=7)
    target = target_factory.fresh()
    if target.adapter_kind != authority_snapshot.target_row.adapter_kind:
        raise ReplicationError("target_composition_changed", code=7)
    bound = target.bind(
        composition.target_id,
        authority_snapshot.target_row.marker_sha256,
    )
    runtime_witness = bound.runtime_identity_witness_sha256()
    if runtime_witness != approved_manifest.approved_runtime_target_identity_sha256:
        raise ReplicationError("target_runtime_identity_changed", code=7)
    inspections = tuple(bound.inspect_state(entry.object()) for entry in source.objects)
    if any(item.target_runtime_identity_sha256 != runtime_witness for item in inspections):
        raise ReplicationError("target_runtime_identity_changed", code=7)
    target_snapshot = TargetSnapshotProjection(
        target_composition_sha256=composition.sha256,
        target_row_sha256=authority_snapshot.target_row.sha256,
        runtime_target_identity_sha256=runtime_witness,
        source_eligibility_sha256=source.sha256,
        destination_inspections=inspections,
        eligible_count=len(inspections),
        absent_count=sum(item.final_state == "absent" for item in inspections),
        exact_count=sum(item.final_state == "exact" for item in inspections),
        transient_present_count=sum(item.transient_state == "present" for item in inspections),
    )
    remaining = project_remaining_work(source, authority_snapshot)
    current_context = build_authority_context(
        identity, authority_snapshot, target_snapshot, source, remaining
    )
    current_manifest = build_candidate_manifest(
        identity, current_context, authority_snapshot, target_snapshot, source, remaining
    )
    if source.sha256 != approved_manifest.source_eligibility_sha256:
        raise ReplicationError("source_changed", code=7)
    if authority_snapshot.sha256 != approved_manifest.pre_action_authority_snapshot_sha256:
        raise ReplicationError("authority_snapshot_changed", code=7)
    if target_snapshot.sha256 != approved_manifest.pre_action_target_snapshot_sha256:
        raise ReplicationError("target_snapshot_changed", code=7)
    if remaining.sha256 != approved_manifest.pre_action_remaining_work_sha256:
        raise ReplicationError("remaining_work_changed", code=7)
    if current_context.sha256 != authority_context.sha256:
        raise ReplicationError("authority_context_changed", code=7)
    if current_manifest.sha256 != approved_manifest.sha256:
        raise ReplicationError("candidate_manifest_changed", code=7)

    connection = authority.connect(database)
    results: list[ExactEntryResult] = []
    published = adopted = verified = 0
    failed_ordinal: int | None = None
    first_finding: str | None = None
    try:
        authority.require_current(connection)
        for entry in approved_manifest.entries:
            obj = entry.object()
            attempted = False
            try:
                if bound.runtime_identity_witness_sha256() != runtime_witness:
                    raise ReplicationError("target_runtime_identity_changed", code=7)
                source = revalidate_source_entry(database, spool_root, obj)
                if source.sha256 != entry.source_eligibility_sha256:
                    raise ReplicationError("source_changed", code=7)
                replica = read_replica_witness(connection, obj)
                replica_sha = replica.sha256
                approved_replica_sha = (
                    entry.prior_replica_absence_sha256
                    if isinstance(replica, ReplicaRowAbsenceProjection)
                    else entry.prior_replica_row_sha256
                )
                if replica_sha != approved_replica_sha:
                    raise ReplicationError("replica_row_changed", code=7)
                inspection = bound.inspect_state(obj)
                if inspection.sha256 != entry.approved_destination_inspection_sha256:
                    raise ReplicationError("destination_changed", code=7)
                if inspection.transient_state != "clean":
                    raise ReplicationError("transient_state_present", code=7)

                if entry.prior_replica_disposition == "unregistered":
                    authority.register_discovered(connection, obj.target_id, (obj,))
                    replica = read_replica_witness(connection, obj)
                    if not isinstance(replica, ReplicaRowProjection) or replica.disposition != "pending":
                        raise ReplicationError("replica_row_presence_changed", code=7)
                elif not isinstance(replica, ReplicaRowProjection) or replica.disposition not in {"pending", "failed-pending"}:
                    raise ReplicationError("replica_row_changed", code=7)

                authority.record_attempt(connection, obj)
                attempted = True
                if revalidate_source_entry(database, spool_root, obj).sha256 != entry.source_eligibility_sha256:
                    raise ReplicationError("source_changed", code=7)
                current = bound.inspect_state(obj)
                if current.sha256 != entry.approved_destination_inspection_sha256:
                    raise ReplicationError("destination_changed", code=7)
                if current.final_state == "exact":
                    bound.verify(obj)
                    result_code = "adopted"
                    adopted += 1
                else:
                    if bound.runtime_identity_witness_sha256() != runtime_witness:
                        raise ReplicationError("target_runtime_identity_changed", code=7)
                    result_code = bound.publish_immutable(spool_root, obj)
                    if result_code != "published":
                        raise ReplicationError("destination_changed", code=7)
                    published += 1
                    bound.verify(obj)
                if bound.runtime_identity_witness_sha256() != runtime_witness:
                    raise ReplicationError("target_runtime_identity_changed", code=7)
                authority.mark_verified(connection, obj)
                final_row = read_replica_witness(connection, obj)
                final_inspection = bound.inspect_state(obj)
                if not isinstance(final_row, ReplicaRowProjection) or final_row.disposition != "verified" or final_inspection.final_state != "exact":
                    raise ReplicationError("verification_failed", code=7)
                verified += 1
                results.append(ExactEntryResult(
                    entry.ordinal, result_code, final_row.sha256,
                    final_inspection.sha256, None,
                ))
            except Exception as exc:
                finding = exc.finding if isinstance(exc, ReplicationError) else "worker_exception"
                if attempted:
                    try:
                        current_row = read_replica_witness(connection, obj)
                        if isinstance(current_row, ReplicaRowProjection) and current_row.disposition in {"pending", "failed-pending"}:
                            authority.record_failure(connection, obj, finding)
                    except Exception:
                        pass
                failed_ordinal = entry.ordinal
                first_finding = finding
                results.append(ExactEntryResult(
                    entry.ordinal, "failed", None, None, finding,
                ))
                break
        if failed_ordinal is not None:
            for entry in approved_manifest.entries[len(results):]:
                results.append(ExactEntryResult(entry.ordinal, "not-run", None, None, None))
    finally:
        connection.close()

    ordered = tuple(results)
    return ExactRunResult(
        status="pass" if failed_ordinal is None else "failed",
        implementation_identity_sha256=identity.sha256,
        authority_context_sha256=authority_context.sha256,
        candidate_manifest_sha256=approved_manifest.sha256,
        runtime_target_identity_sha256=runtime_witness,
        entry_results=ordered,
        entry_results_sha256=canonical_sha256(ordered),
        candidate_count=approved_manifest.candidate_count,
        processed_count=sum(item.result_code in {"published", "adopted", "failed"} for item in ordered),
        published_count=published,
        adopted_count=adopted,
        verified_count=verified,
        failed_ordinal=failed_ordinal,
        finding_code=first_finding,
    )
