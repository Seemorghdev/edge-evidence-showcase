"""Provider facade for the proven mounted-NFSv4 replication target."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from packages.agent_contracts.canonical import canonical_sha256
from packages.replication.contracts.model import ReplicaObject, ReplicationError
from packages.replication.contracts.target import (
    DestinationInspection,
    DestinationState,
    PublishResult,
    TargetCompositionProjection,
)

from . import filesystem, inspection
from .model import ADAPTER_KIND


@dataclass(frozen=True)
class _BoundNfsTarget:
    root: Path
    target_id: str
    marker_sha256: str
    _runtime_identity: tuple[int, int] = field(repr=False)
    adapter_kind: str = ADAPTER_KIND

    def _composition_sha256(self) -> str:
        try:
            root_realpath = self.root.resolve(strict=True).as_posix()
        except OSError as exc:
            raise filesystem._target_error(exc) from exc
        return TargetCompositionProjection(
            target_id=self.target_id,
            adapter_kind=self.adapter_kind,
            location={"root_realpath": root_realpath},
        ).sha256

    def validate_identity(self) -> None:
        filesystem.validate_target_identity(
            self.root,
            self.target_id,
            self.marker_sha256,
            expected_runtime_identity=self._runtime_identity,
        )

    def runtime_identity_witness_sha256(self) -> str:
        evidence = filesystem.runtime_identity_evidence(
            self.root,
            self.target_id,
            self.marker_sha256,
            expected_runtime_identity=self._runtime_identity,
        )
        adapter_witness_sha256 = canonical_sha256(
            {
                "schema": "replication-nfs-runtime-identity.v1",
                **evidence,
            }
        )
        return canonical_sha256(
            {
                "schema": "replication-runtime-target-identity.v1",
                "adapter_kind": self.adapter_kind,
                "target_id": self.target_id,
                "marker_sha256": self.marker_sha256,
                "target_composition_sha256": self._composition_sha256(),
                "adapter_runtime_witness_sha256": adapter_witness_sha256,
            }
        )

    def inspect_state(self, obj: ReplicaObject) -> DestinationInspection:
        if obj.target_id != self.target_id:
            raise ReplicationError("target_identity_mismatch", code=4)
        witness = self.runtime_identity_witness_sha256()
        result = inspection.inspect_destination_state(
            self.root,
            obj,
            target_runtime_identity_sha256=witness,
        )
        if self.runtime_identity_witness_sha256() != witness:
            raise ReplicationError("target_identity_mismatch", code=4)
        return result

    def cleanup_transient(self, obj: ReplicaObject) -> bool:
        return inspection.cleanup_owned_partial_existing(self.root, obj)

    def inspect(self, obj: ReplicaObject) -> DestinationState:
        return inspection.reconcile_destination_state(self.root, obj)  # type: ignore[return-value]

    def publish_immutable(self, spool_root: Path, obj: ReplicaObject) -> PublishResult:
        return filesystem.publish_object(
            spool_root,
            self.root,
            obj,
            target_id=self.target_id,
            marker_sha256=self.marker_sha256,
            runtime_identity=self._runtime_identity,
        )  # type: ignore[return-value]

    def verify(self, obj: ReplicaObject) -> None:
        inspection.verify_existing_replica(self.root, obj)


@dataclass(frozen=True)
class NfsTarget:
    """Construct/bind the existing mounted-NFSv4 target behind neutral semantics."""

    root: Path
    adapter_kind: str = ADAPTER_KIND

    def initialize(self, target_id: str) -> str:
        return filesystem.initialize_marker(self.root, target_id)

    def bind(self, target_id: str, marker_sha256: str) -> _BoundNfsTarget:
        runtime_identity = filesystem.validate_target_identity(
            self.root,
            target_id,
            marker_sha256,
        )
        return _BoundNfsTarget(
            root=self.root,
            target_id=target_id,
            marker_sha256=marker_sha256,
            _runtime_identity=runtime_identity,
        )
