"""Exact owner-approvable manifest for one bounded replication action."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from packages.agent_contracts.canonical import canonical_sha256
from packages.agent_contracts.model import Service
from packages.replication.contracts.model import ReplicaObject, ReplicationError

from .implementation_identity import ImplementationIdentity
from .projections import (
    AuthoritySnapshotProjection,
    RemainingWorkProjection,
    SourceEligibilityProjection,
    TargetSnapshotProjection,
)


@dataclass(frozen=True)
class ReplicationAuthorityContext:
    schema: ClassVar[str] = "replication-authority-context.v1"
    service: Service
    canonical_repository_host: str
    canonical_repository_id: str
    canonical_repository_full_name: str
    canonical_commit: str
    implementation_identity_sha256: str
    database_schema_version: int
    target_row_sha256: str
    target_composition_sha256: str
    runtime_target_identity_sha256: str
    source_eligibility_sha256: str
    pre_action_authority_snapshot_sha256: str
    pre_action_target_snapshot_sha256: str
    pre_action_remaining_work_sha256: str
    proof_class: str

    def __post_init__(self) -> None:
        if self.service is not Service.REPLICATION or self.database_schema_version != 10:
            raise ReplicationError("authority_context_changed", code=7)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, order=True)
class CandidateEntry:
    schema: ClassVar[str] = "replication-candidate-entry.v1"
    ordinal: int
    target_id: str
    object_kind: str
    relative_uri: str
    expected_byte_size: int
    expected_sha256: str
    source_eligibility_sha256: str
    prior_replica_disposition: str
    prior_replica_row_sha256: str | None
    prior_replica_absence_sha256: str | None
    approved_destination_state: str
    approved_destination_witness_sha256: str
    approved_transient_state: str
    approved_transient_witness_sha256: str
    approved_destination_inspection_sha256: str

    def __post_init__(self) -> None:
        if self.prior_replica_disposition not in {"unregistered", "pending", "failed-pending"}:
            raise ReplicationError("candidate_manifest_changed", code=7)
        if (self.prior_replica_row_sha256 is None) == (self.prior_replica_absence_sha256 is None):
            raise ReplicationError("candidate_manifest_changed", code=7)
        if self.approved_destination_state not in {"absent", "exact"} or self.approved_transient_state != "clean":
            raise ReplicationError("candidate_manifest_changed", code=7)

    def object(self) -> ReplicaObject:
        return ReplicaObject(
            target_id=self.target_id,
            object_kind=self.object_kind,
            relative_uri=self.relative_uri,
            expected_byte_size=self.expected_byte_size,
            expected_sha256=self.expected_sha256,
        )


@dataclass(frozen=True)
class CandidateManifest:
    schema: ClassVar[str] = "replication-candidate-manifest.v1"
    implementation_identity_sha256: str
    authority_context_sha256: str
    target_composition_sha256: str
    target_row_sha256: str
    approved_runtime_target_identity_sha256: str
    source_eligibility_sha256: str
    pre_action_authority_snapshot_sha256: str
    pre_action_target_snapshot_sha256: str
    pre_action_remaining_work_sha256: str
    entries_sha256: str
    entries: tuple[CandidateEntry, ...]
    candidate_count: int

    def __post_init__(self) -> None:
        if self.candidate_count <= 0 or self.candidate_count != len(self.entries):
            raise ReplicationError("candidate_manifest_changed", code=7)
        if tuple(entry.ordinal for entry in self.entries) != tuple(range(len(self.entries))):
            raise ReplicationError("candidate_manifest_changed", code=7)
        keys = tuple((entry.target_id, entry.object_kind, entry.relative_uri) for entry in self.entries)
        if keys != tuple(sorted(set(keys))) or self.entries_sha256 != canonical_sha256(self.entries):
            raise ReplicationError("candidate_manifest_changed", code=7)

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


def build_authority_context(
    identity: ImplementationIdentity,
    authority_snapshot: AuthoritySnapshotProjection,
    target_snapshot: TargetSnapshotProjection,
    source: SourceEligibilityProjection,
    remaining: RemainingWorkProjection,
) -> ReplicationAuthorityContext:
    return ReplicationAuthorityContext(
        service=Service.REPLICATION,
        canonical_repository_host=identity.canonical_repository_host,
        canonical_repository_id=identity.canonical_repository_id,
        canonical_repository_full_name=identity.canonical_repository_full_name,
        canonical_commit=identity.implementation_commit,
        implementation_identity_sha256=identity.sha256,
        database_schema_version=10,
        target_row_sha256=authority_snapshot.target_row.sha256,
        target_composition_sha256=target_snapshot.target_composition_sha256,
        runtime_target_identity_sha256=target_snapshot.runtime_target_identity_sha256,
        source_eligibility_sha256=source.sha256,
        pre_action_authority_snapshot_sha256=authority_snapshot.sha256,
        pre_action_target_snapshot_sha256=target_snapshot.sha256,
        pre_action_remaining_work_sha256=remaining.sha256,
        proof_class="synthetic-or-application-owned",
    )


def build_candidate_manifest(
    identity: ImplementationIdentity,
    context: ReplicationAuthorityContext,
    authority_snapshot: AuthoritySnapshotProjection,
    target_snapshot: TargetSnapshotProjection,
    source: SourceEligibilityProjection,
    remaining: RemainingWorkProjection,
) -> CandidateManifest:
    inspections = {
        (item.object_kind, item.relative_uri): item
        for item in target_snapshot.destination_inspections
    }
    candidates = []
    for work in remaining.entries:
        if work.replica_disposition == "verified":
            continue
        inspection = inspections.get((work.object_kind, work.relative_uri))
        if inspection is None or inspection.transient_state != "clean":
            raise ReplicationError("transient_state_present", code=7)
        candidates.append((work, inspection))
    candidates.sort(key=lambda pair: (pair[0].target_id, pair[0].object_kind, pair[0].relative_uri))
    entries = tuple(
        CandidateEntry(
            ordinal=ordinal,
            target_id=work.target_id,
            object_kind=work.object_kind,
            relative_uri=work.relative_uri,
            expected_byte_size=work.expected_byte_size,
            expected_sha256=work.expected_sha256,
            source_eligibility_sha256=work.source_eligibility_sha256,
            prior_replica_disposition=work.replica_disposition,
            prior_replica_row_sha256=work.replica_row_sha256,
            prior_replica_absence_sha256=work.replica_absence_sha256,
            approved_destination_state=inspection.final_state,
            approved_destination_witness_sha256=inspection.destination_witness_sha256,
            approved_transient_state=inspection.transient_state,
            approved_transient_witness_sha256=inspection.transient_witness_sha256,
            approved_destination_inspection_sha256=inspection.sha256,
        )
        for ordinal, (work, inspection) in enumerate(candidates)
    )
    if not entries:
        raise ReplicationError("candidate_manifest_empty", code=7)
    return CandidateManifest(
        implementation_identity_sha256=identity.sha256,
        authority_context_sha256=context.sha256,
        target_composition_sha256=target_snapshot.target_composition_sha256,
        target_row_sha256=authority_snapshot.target_row.sha256,
        approved_runtime_target_identity_sha256=target_snapshot.runtime_target_identity_sha256,
        source_eligibility_sha256=source.sha256,
        pre_action_authority_snapshot_sha256=authority_snapshot.sha256,
        pre_action_target_snapshot_sha256=target_snapshot.sha256,
        pre_action_remaining_work_sha256=remaining.sha256,
        entries_sha256=canonical_sha256(entries),
        entries=entries,
        candidate_count=len(entries),
    )
