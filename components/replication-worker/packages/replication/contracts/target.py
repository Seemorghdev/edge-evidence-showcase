"""Semantic target interface owned by replication core, not by any provider."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Protocol, runtime_checkable

from packages.agent_contracts.canonical import canonical_sha256

from .model import ReplicaObject

DestinationState = Literal["absent", "exact"]
TransientState = Literal["clean", "present"]
PublishResult = Literal["published", "adopted"]


def _is_lower_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class TargetCompositionProjection:
    """Canonical, non-secret application composition for one target."""

    schema: ClassVar[str] = "replication-target-composition.v1"

    target_id: str
    adapter_kind: str
    location: dict[str, str]

    def __post_init__(self) -> None:
        if not self.target_id or not self.adapter_kind:
            raise ValueError("target composition identifiers must be non-empty")
        if not isinstance(self.location, dict) or not self.location:
            raise ValueError("target composition location must be a non-empty mapping")
        if any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            for key, value in self.location.items()
        ):
            raise ValueError("target composition location must contain string fields")
        object.__setattr__(self, "location", dict(self.location))

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True)
class DestinationInspection:
    """Read-only provider-neutral destination and transient projection."""

    schema: ClassVar[str] = "replication-destination-inspection.v1"

    target_runtime_identity_sha256: str
    target_id: str
    object_kind: str
    relative_uri: str
    expected_byte_size: int
    expected_sha256: str
    final_state: DestinationState
    transient_state: TransientState
    destination_witness_sha256: str
    transient_witness_sha256: str

    def __post_init__(self) -> None:
        for value in (
            self.target_runtime_identity_sha256,
            self.expected_sha256,
            self.destination_witness_sha256,
            self.transient_witness_sha256,
        ):
            if not _is_lower_sha256(value):
                raise ValueError("inspection digests must be lowercase SHA-256 values")
        if not self.target_id or not self.object_kind or not self.relative_uri:
            raise ValueError("inspection identifiers must be non-empty")
        if self.expected_byte_size < 0:
            raise ValueError("inspection byte size must be non-negative")

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


@runtime_checkable
class BoundReplicationTarget(Protocol):
    """One target whose identity has been bound for a bounded worker invocation."""

    adapter_kind: str
    target_id: str
    marker_sha256: str

    def validate_identity(self) -> None:
        """Fail if the runtime target no longer matches the bound identity."""

    def runtime_identity_witness_sha256(self) -> str:
        """Return only the opaque lowercase SHA-256 runtime identity witness."""

    def inspect_state(self, obj: ReplicaObject) -> DestinationInspection:
        """Read destination and transient state without mutation or cleanup."""

    def cleanup_transient(self, obj: ReplicaObject) -> bool:
        """Remove only adapter-owned transient state for ``obj`` when present."""

    def inspect(self, obj: ReplicaObject) -> DestinationState:
        """Return absent/exact; conflicting destination bytes fail closed."""

    def publish_immutable(self, spool_root: Path, obj: ReplicaObject) -> PublishResult:
        """Create only if absent or adopt exact existing bytes; never overwrite."""

    def verify(self, obj: ReplicaObject) -> None:
        """Read back and verify expected object size/content identity."""


@runtime_checkable
class ReplicationTarget(Protocol):
    """Provider-specific target implementing provider-neutral target semantics."""

    adapter_kind: str

    def initialize(self, target_id: str) -> str:
        """Initialize/validate target identity and return its canonical marker digest."""

    def bind(self, target_id: str, marker_sha256: str) -> BoundReplicationTarget:
        """Bind one runtime identity for a bounded convergence invocation."""


@runtime_checkable
class ReplicationTargetFactory(Protocol):
    """Application-owned composition that returns a fresh target every time."""

    composition: TargetCompositionProjection

    def fresh(self) -> ReplicationTarget:
        """Return a newly constructed, unbound target object without provider mutation."""
