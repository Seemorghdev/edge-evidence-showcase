"""Typed canonical read projections for the exact replication action."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import ClassVar, Literal

from packages.agent_contracts.canonical import canonical_sha256
from packages.replication.contracts.model import ReplicaObject, ReplicationError
from packages.replication.contracts.target import (
    DestinationInspection,
    ReplicationTargetFactory,
    TargetCompositionProjection,
)
from packages.replication.core import authority
from packages.replication.core.source import local_size_and_hash

ReplicaDisposition = Literal["unregistered", "pending", "failed-pending", "verified"]
OutcomeCode = Literal[
    "verified-exact",
    "pending-exact",
    "pending-absent",
    "unregistered-exact",
    "unregistered-absent",
    "authority-conflict",
    "destination-conflict",
    "transient-present",
    "source-changed",
    "unavailable",
]


@dataclass(frozen=True, order=True)
class TargetRowProjection:
    schema: ClassVar[str] = "replication-target-row.v1"
    target_id: str
    adapter_kind: str
    marker_sha256: str
    created_at: str

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, order=True)
class ReplicaRowProjection:
    schema: ClassVar[str] = "replication-replica-row.v1"
    target_id: str
    object_kind: str
    relative_uri: str
    expected_byte_size: int
    expected_sha256: str
    state: str
    attempt_count: int
    last_error: str | None
    created_at: str
    verified_at: str | None

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)

    @property
    def disposition(self) -> ReplicaDisposition:
        if self.state == "VERIFIED":
            return "verified"
        return "pending" if self.last_error is None else "failed-pending"

    def object(self) -> ReplicaObject:
        return ReplicaObject(
            target_id=self.target_id,
            object_kind=self.object_kind,
            relative_uri=self.relative_uri,
            expected_byte_size=self.expected_byte_size,
            expected_sha256=self.expected_sha256,
        )


@dataclass(frozen=True, order=True)
class ReplicaRowAbsenceProjection:
    schema: ClassVar[str] = "replication-replica-row-absence.v1"
    target_id: str
    object_kind: str
    relative_uri: str
    row_count: int = 0

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, order=True)
class SourceReferenceProjection:
    schema: ClassVar[str] = "replication-source-reference.v1"
    source_table: str
    source_key_name: str
    source_key: str
    source_field: str
    state_predicate: str


@dataclass(frozen=True, order=True)
class SourceEligibilityEntry:
    schema: ClassVar[str] = "replication-source-eligibility-entry.v1"
    target_id: str
    object_kind: str
    relative_uri: str
    expected_byte_size: int
    expected_sha256: str
    local_byte_size: int
    local_sha256: str
    source_references: tuple[SourceReferenceProjection, ...]

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)

    def object(self) -> ReplicaObject:
        return ReplicaObject(
            target_id=self.target_id,
            object_kind=self.object_kind,
            relative_uri=self.relative_uri,
            expected_byte_size=self.expected_byte_size,
            expected_sha256=self.expected_sha256,
        )


@dataclass(frozen=True)
class SourceEligibilityProjection:
    schema: ClassVar[str] = "replication-source-eligibility.v1"
    target_id: str
    objects: tuple[SourceEligibilityEntry, ...]
    object_count: int

    def __post_init__(self) -> None:
        if self.object_count != len(self.objects) or tuple(sorted(set(self.objects))) != self.objects:
            raise ReplicationError("source_authority_conflict", code=7)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True)
class AuthoritySnapshotProjection:
    schema: ClassVar[str] = "replication-authority-snapshot.v1"
    target_row: TargetRowProjection
    replica_rows: tuple[ReplicaRowProjection, ...]
    replica_row_count: int
    pending_count: int
    failed_pending_count: int
    verified_count: int

    def __post_init__(self) -> None:
        if self.replica_row_count != len(self.replica_rows):
            raise ReplicationError("database_integrity_failure", code=7)
        counts = (
            sum(row.disposition == "pending" for row in self.replica_rows),
            sum(row.disposition == "failed-pending" for row in self.replica_rows),
            sum(row.disposition == "verified" for row in self.replica_rows),
        )
        if counts != (self.pending_count, self.failed_pending_count, self.verified_count):
            raise ReplicationError("database_integrity_failure", code=7)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True)
class TargetSnapshotProjection:
    schema: ClassVar[str] = "replication-target-snapshot.v1"
    target_composition_sha256: str
    target_row_sha256: str
    runtime_target_identity_sha256: str
    source_eligibility_sha256: str
    destination_inspections: tuple[DestinationInspection, ...]
    eligible_count: int
    absent_count: int
    exact_count: int
    transient_present_count: int

    def __post_init__(self) -> None:
        if self.eligible_count != len(self.destination_inspections):
            raise ReplicationError("target_snapshot_changed", code=7)
        if self.absent_count + self.exact_count != self.eligible_count:
            raise ReplicationError("target_snapshot_changed", code=7)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, order=True)
class RemainingWorkEntry:
    schema: ClassVar[str] = "replication-remaining-work-entry.v1"
    source_eligibility_sha256: str
    target_id: str
    object_kind: str
    relative_uri: str
    expected_byte_size: int
    expected_sha256: str
    replica_disposition: ReplicaDisposition
    replica_row_sha256: str | None
    replica_absence_sha256: str | None


@dataclass(frozen=True)
class RemainingWorkProjection:
    schema: ClassVar[str] = "replication-remaining-work.v1"
    target_id: str
    source_eligibility_sha256: str
    authority_snapshot_sha256: str
    entries: tuple[RemainingWorkEntry, ...]
    eligible_count: int
    unregistered_count: int
    pending_count: int
    failed_pending_count: int
    verified_count: int
    remaining_count: int

    def __post_init__(self) -> None:
        counts = (
            sum(entry.replica_disposition == "unregistered" for entry in self.entries),
            sum(entry.replica_disposition == "pending" for entry in self.entries),
            sum(entry.replica_disposition == "failed-pending" for entry in self.entries),
            sum(entry.replica_disposition == "verified" for entry in self.entries),
        )
        if self.eligible_count != len(self.entries) or counts != (
            self.unregistered_count,
            self.pending_count,
            self.failed_pending_count,
            self.verified_count,
        ):
            raise ReplicationError("replica_authority_conflict", code=7)
        if self.remaining_count != sum(counts[:3]):
            raise ReplicationError("replica_authority_conflict", code=7)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, order=True)
class PartialOutcomeEntry:
    schema: ClassVar[str] = "replication-partial-outcome-entry.v1"
    ordinal: int
    target_id: str
    object_kind: str
    relative_uri: str
    expected_byte_size: int
    expected_sha256: str
    pre_source_eligibility_sha256: str
    post_source_eligibility_sha256: str | None
    pre_replica_witness_sha256: str
    post_replica_row_sha256: str | None
    post_replica_absence_sha256: str | None
    pre_destination_inspection_sha256: str
    post_destination_inspection_sha256: str | None
    attempt_count_before: int
    attempt_count_after: int | None
    attempt_delta: int | None
    outcome_code: OutcomeCode
    finding_codes: tuple[str, ...]


@dataclass(frozen=True)
class PartialOutcomeSet:
    schema: ClassVar[str] = "replication-partial-outcome-set.v1"
    candidate_manifest_sha256: str
    entries: tuple[PartialOutcomeEntry, ...]
    entry_count: int
    verified_exact_count: int
    incomplete_count: int
    unavailable_count: int
    partial_execution: bool

    def __post_init__(self) -> None:
        if tuple(entry.ordinal for entry in self.entries) != tuple(range(len(self.entries))):
            raise ReplicationError("verification_ambiguous", code=7)
        verified = sum(entry.outcome_code == "verified-exact" for entry in self.entries)
        unavailable = sum(entry.outcome_code == "unavailable" for entry in self.entries)
        if (
            self.entry_count != len(self.entries)
            or self.verified_exact_count != verified
            or self.incomplete_count != self.entry_count - verified
            or self.unavailable_count != unavailable
            or self.partial_execution != (verified > 0 and verified < self.entry_count)
        ):
            raise ReplicationError("verification_ambiguous", code=7)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


def _target_row(connection: sqlite3.Connection, target_id: str) -> TargetRowProjection:
    rows = connection.execute(
        "SELECT target_id, adapter_kind, marker_sha256, created_at FROM replica_targets WHERE target_id=?",
        (target_id,),
    ).fetchall()
    if len(rows) != 1:
        raise ReplicationError("target_row_changed", code=7)
    return TargetRowProjection(*(str(value) for value in rows[0]))


def _replica_rows(connection: sqlite3.Connection, target_id: str) -> tuple[ReplicaRowProjection, ...]:
    rows = connection.execute(
        "SELECT target_id, object_kind, relative_uri, expected_byte_size, expected_sha256, state, attempt_count, last_error, created_at, verified_at "
        "FROM replica_objects WHERE target_id=? ORDER BY target_id, object_kind, relative_uri",
        (target_id,),
    ).fetchall()
    return tuple(
        ReplicaRowProjection(
            target_id=str(row[0]), object_kind=str(row[1]), relative_uri=str(row[2]),
            expected_byte_size=int(row[3]), expected_sha256=str(row[4]), state=str(row[5]),
            attempt_count=int(row[6]), last_error=None if row[7] is None else str(row[7]),
            created_at=str(row[8]), verified_at=None if row[9] is None else str(row[9]),
        )
        for row in rows
    )


def read_replica_witness(
    connection: sqlite3.Connection,
    obj: ReplicaObject,
) -> ReplicaRowProjection | ReplicaRowAbsenceProjection:
    rows = tuple(row for row in _replica_rows(connection, obj.target_id) if (row.object_kind, row.relative_uri) == (obj.object_kind, obj.relative_uri))
    if not rows:
        return ReplicaRowAbsenceProjection(obj.target_id, obj.object_kind, obj.relative_uri)
    if len(rows) != 1:
        raise ReplicationError("replica_authority_conflict", code=7)
    row = rows[0]
    if (row.expected_byte_size, row.expected_sha256) != (obj.expected_byte_size, obj.expected_sha256):
        raise ReplicationError("replica_authority_conflict", code=7)
    return row


def project_authority_snapshot(database: Path, target_id: str, *, readonly: bool = True) -> AuthoritySnapshotProjection:
    connection = authority.connect(database, readonly=readonly)
    try:
        authority.require_current(connection)
        target = _target_row(connection, target_id)
        rows = _replica_rows(connection, target_id)
        return AuthoritySnapshotProjection(
            target_row=target,
            replica_rows=rows,
            replica_row_count=len(rows),
            pending_count=sum(row.disposition == "pending" for row in rows),
            failed_pending_count=sum(row.disposition == "failed-pending" for row in rows),
            verified_count=sum(row.disposition == "verified" for row in rows),
        )
    finally:
        connection.close()


def _source_references(connection: sqlite3.Connection, obj: ReplicaObject) -> tuple[SourceReferenceProjection, ...]:
    references: list[SourceReferenceProjection] = []
    for artifact_id, storage_uri, manifest_uri in connection.execute(
        "SELECT artifact_id, storage_uri, manifest_uri FROM artifacts ORDER BY artifact_id"
    ):
        if obj.object_kind == "artifact_content" and str(storage_uri) == obj.relative_uri:
            references.append(SourceReferenceProjection("artifacts", "artifact_id", str(artifact_id), "storage_uri", "every-row"))
        if obj.object_kind == "artifact_manifest" and str(manifest_uri) == obj.relative_uri:
            references.append(SourceReferenceProjection("artifacts", "artifact_id", str(artifact_id), "manifest_uri", "every-row"))
    if obj.object_kind == "occurrence_assertion":
        for occurrence_id, manifest_uri in connection.execute(
            "SELECT occurrence_id, manifest_uri FROM capture_occurrence_assertions ORDER BY occurrence_id"
        ):
            if str(manifest_uri) == obj.relative_uri:
                references.append(SourceReferenceProjection("capture_occurrence_assertions", "occurrence_id", str(occurrence_id), "manifest_uri", "every-row"))
    if obj.object_kind == "recording_original":
        for recording_id, storage_uri in connection.execute(
            "SELECT recording_id, storage_uri FROM recording_imports WHERE state='COMPLETE' ORDER BY recording_id"
        ):
            if str(storage_uri) == obj.relative_uri:
                references.append(SourceReferenceProjection("recording_imports", "recording_id", str(recording_id), "storage_uri", "state=COMPLETE"))
    if not references:
        raise ReplicationError("source_authority_conflict", code=7)
    return tuple(sorted(set(references)))


def project_source_eligibility(database: Path, spool_root: Path, target_id: str) -> SourceEligibilityProjection:
    discovered = authority.discover(database, spool_root, target_id)
    connection = authority.connect(database, readonly=True)
    try:
        authority.require_current(connection)
        entries = []
        for obj in discovered:
            size, digest = local_size_and_hash(spool_root, obj.relative_uri)
            if (size, digest) != (obj.expected_byte_size, obj.expected_sha256):
                raise ReplicationError("local_source_corrupt", code=6)
            entries.append(SourceEligibilityEntry(
                target_id=obj.target_id, object_kind=obj.object_kind, relative_uri=obj.relative_uri,
                expected_byte_size=obj.expected_byte_size, expected_sha256=obj.expected_sha256,
                local_byte_size=size, local_sha256=digest,
                source_references=_source_references(connection, obj),
            ))
        return SourceEligibilityProjection(target_id, tuple(sorted(set(entries))), len(entries))
    finally:
        connection.close()


def project_target_snapshot(
    database: Path,
    factory: ReplicationTargetFactory,
    source: SourceEligibilityProjection,
) -> TargetSnapshotProjection:
    authority_snapshot = project_authority_snapshot(database, source.target_id)
    composition: TargetCompositionProjection = factory.composition
    if composition.target_id != source.target_id:
        raise ReplicationError("target_composition_changed", code=7)
    target = factory.fresh()
    if target.adapter_kind != authority_snapshot.target_row.adapter_kind:
        raise ReplicationError("target_composition_changed", code=7)
    bound = target.bind(source.target_id, authority_snapshot.target_row.marker_sha256)
    runtime = bound.runtime_identity_witness_sha256()
    inspections = tuple(bound.inspect_state(entry.object()) for entry in source.objects)
    if any(item.target_runtime_identity_sha256 != runtime for item in inspections):
        raise ReplicationError("target_runtime_identity_changed", code=7)
    return TargetSnapshotProjection(
        target_composition_sha256=composition.sha256,
        target_row_sha256=authority_snapshot.target_row.sha256,
        runtime_target_identity_sha256=runtime,
        source_eligibility_sha256=source.sha256,
        destination_inspections=inspections,
        eligible_count=len(inspections),
        absent_count=sum(item.final_state == "absent" for item in inspections),
        exact_count=sum(item.final_state == "exact" for item in inspections),
        transient_present_count=sum(item.transient_state == "present" for item in inspections),
    )


def project_remaining_work(
    source: SourceEligibilityProjection,
    authority_snapshot: AuthoritySnapshotProjection,
) -> RemainingWorkProjection:
    rows = {(row.object_kind, row.relative_uri): row for row in authority_snapshot.replica_rows}
    eligible_keys = {(entry.object_kind, entry.relative_uri) for entry in source.objects}
    if any((row.object_kind, row.relative_uri) not in eligible_keys for row in authority_snapshot.replica_rows):
        raise ReplicationError("replica_source_orphan", code=7)
    entries = []
    for source_entry in source.objects:
        row = rows.get((source_entry.object_kind, source_entry.relative_uri))
        if row is None:
            absence = ReplicaRowAbsenceProjection(source.target_id, source_entry.object_kind, source_entry.relative_uri)
            disposition: ReplicaDisposition = "unregistered"
            row_sha = None
            absence_sha = absence.sha256
        else:
            if (row.expected_byte_size, row.expected_sha256) != (source_entry.expected_byte_size, source_entry.expected_sha256):
                raise ReplicationError("replica_authority_conflict", code=7)
            disposition = row.disposition
            row_sha = row.sha256
            absence_sha = None
        entries.append(RemainingWorkEntry(
            source_eligibility_sha256=source_entry.sha256,
            target_id=source_entry.target_id,
            object_kind=source_entry.object_kind,
            relative_uri=source_entry.relative_uri,
            expected_byte_size=source_entry.expected_byte_size,
            expected_sha256=source_entry.expected_sha256,
            replica_disposition=disposition,
            replica_row_sha256=row_sha,
            replica_absence_sha256=absence_sha,
        ))
    ordered = tuple(sorted(entries))
    counts = tuple(sum(entry.replica_disposition == value for entry in ordered) for value in ("unregistered", "pending", "failed-pending", "verified"))
    return RemainingWorkProjection(
        target_id=source.target_id,
        source_eligibility_sha256=source.sha256,
        authority_snapshot_sha256=authority_snapshot.sha256,
        entries=ordered,
        eligible_count=len(ordered),
        unregistered_count=counts[0], pending_count=counts[1], failed_pending_count=counts[2],
        verified_count=counts[3], remaining_count=sum(counts[:3]),
    )


def source_entry_by_key(source: SourceEligibilityProjection, obj: ReplicaObject) -> SourceEligibilityEntry:
    matches = tuple(entry for entry in source.objects if (entry.object_kind, entry.relative_uri) == (obj.object_kind, obj.relative_uri))
    if len(matches) != 1 or matches[0].object() != obj:
        raise ReplicationError("source_changed", code=7)
    return matches[0]


def revalidate_source_entry(database: Path, spool_root: Path, obj: ReplicaObject) -> SourceEligibilityEntry:
    """Reconstruct one approved source entry without target-wide discovery."""

    connection = authority.connect(database, readonly=True)
    try:
        authority.require_current(connection)
        references = _source_references(connection, obj)
        matched = False
        if obj.object_kind == "artifact_content":
            rows = connection.execute(
                "SELECT byte_size, digest_value FROM artifacts WHERE storage_uri=?",
                (obj.relative_uri,),
            ).fetchall()
            matched = len(rows) == 1 and (int(rows[0][0]), str(rows[0][1])) == (
                obj.expected_byte_size, obj.expected_sha256
            )
        elif obj.object_kind in {"artifact_manifest", "occurrence_assertion"}:
            table = "artifacts" if obj.object_kind == "artifact_manifest" else "capture_occurrence_assertions"
            rows = connection.execute(
                f"SELECT manifest_sha256 FROM {table} WHERE manifest_uri=?",
                (obj.relative_uri,),
            ).fetchall()
            matched = len(rows) == 1 and str(rows[0][0]) == obj.expected_sha256
        elif obj.object_kind == "recording_original":
            rows = connection.execute(
                "SELECT byte_size, digest_value FROM recording_imports WHERE storage_uri=? AND state='COMPLETE'",
                (obj.relative_uri,),
            ).fetchall()
            matched = len(rows) == 1 and (int(rows[0][0]), str(rows[0][1])) == (
                obj.expected_byte_size, obj.expected_sha256
            )
        if not matched:
            raise ReplicationError("source_changed", code=7)
        size, digest = local_size_and_hash(spool_root, obj.relative_uri)
        if (size, digest) != (obj.expected_byte_size, obj.expected_sha256):
            raise ReplicationError("source_changed", code=7)
        return SourceEligibilityEntry(
            target_id=obj.target_id,
            object_kind=obj.object_kind,
            relative_uri=obj.relative_uri,
            expected_byte_size=obj.expected_byte_size,
            expected_sha256=obj.expected_sha256,
            local_byte_size=size,
            local_sha256=digest,
            source_references=references,
        )
    finally:
        connection.close()
