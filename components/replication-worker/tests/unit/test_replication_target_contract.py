"""Unit proofs for the provider-neutral semantic target boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.replication.adapters.nfs.target import NfsTarget
from packages.replication.contracts.target import (
    BoundReplicationTarget,
    DestinationInspection,
    ReplicationTarget,
    ReplicationTargetFactory,
    TargetCompositionProjection,
)
from packages.replication.model import ReplicaObject, ReplicationError


def _obj(*, target_id: str = "backup") -> ReplicaObject:
    return ReplicaObject(
        target_id=target_id,
        object_kind="artifact_content",
        relative_uri="file:sha256/aa/object.bin",
        expected_byte_size=3,
        expected_sha256="0" * 64,
    )


def test_composition_projection_digest_is_stable_and_order_independent() -> None:
    first = TargetCompositionProjection(
        target_id="backup",
        adapter_kind="gcs",
        location={
            "bucket_name": "example-evidence-bucket",
            "prefix": "replicas/dev",
        },
    )
    second = TargetCompositionProjection(
        target_id="backup",
        adapter_kind="gcs",
        location={
            "prefix": "replicas/dev",
            "bucket_name": "example-evidence-bucket",
        },
    )
    assert first == second
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64
    assert first.sha256 == first.sha256.lower()


def test_application_factory_protocol_returns_distinct_targets() -> None:
    composition = TargetCompositionProjection(
        target_id="backup",
        adapter_kind="mounted_nfs_v4",
        location={"root_realpath": "/replica"},
    )

    class Factory:
        def __init__(self) -> None:
            self.composition = composition

        def fresh(self) -> NfsTarget:
            return NfsTarget(Path(self.composition.location["root_realpath"]))

    factory = Factory()
    assert isinstance(factory, ReplicationTargetFactory)
    first = factory.fresh()
    second = factory.fresh()
    assert first is not second
    assert first == second


def test_nfs_target_satisfies_neutral_target_contract() -> None:
    target = NfsTarget(Path("/replica"))
    assert isinstance(target, ReplicationTarget)
    assert target.adapter_kind == "mounted_nfs_v4"


def test_destination_projection_rejects_non_sha256_witnesses() -> None:
    with pytest.raises(ValueError):
        DestinationInspection(
            target_runtime_identity_sha256="not-a-digest",
            target_id="backup",
            object_kind="artifact_content",
            relative_uri="file:sha256/aa/object.bin",
            expected_byte_size=3,
            expected_sha256="0" * 64,
            final_state="absent",
            transient_state="clean",
            destination_witness_sha256="1" * 64,
            transient_witness_sha256="2" * 64,
        )


def test_bound_nfs_target_forwards_legacy_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.replication.adapters.nfs import target as module

    calls: list[str] = []
    monkeypatch.setattr(
        module.filesystem,
        "validate_target_identity",
        lambda *args, **kwargs: (11, 22),
    )
    monkeypatch.setattr(
        module.inspection,
        "cleanup_owned_partial_existing",
        lambda *args, **kwargs: calls.append("cleanup") or True,
    )
    monkeypatch.setattr(
        module.inspection,
        "reconcile_destination_state",
        lambda *args, **kwargs: calls.append("inspect") or "exact",
    )
    monkeypatch.setattr(
        module.filesystem,
        "publish_object",
        lambda *args, **kwargs: calls.append("publish") or "adopted",
    )
    monkeypatch.setattr(
        module.inspection,
        "verify_existing_replica",
        lambda *args, **kwargs: calls.append("verify"),
    )

    bound = NfsTarget(Path("/replica")).bind("backup", "1" * 64)
    assert isinstance(bound, BoundReplicationTarget)
    assert bound.cleanup_transient(_obj()) is True
    assert bound.inspect(_obj()) == "exact"
    assert bound.publish_immutable(Path("/spool"), _obj()) == "adopted"
    bound.verify(_obj())
    assert calls == ["cleanup", "inspect", "publish", "verify"]


def test_bound_nfs_witness_and_state_inspection_are_opaque_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.replication.adapters.nfs import target as module

    calls: list[str] = []
    monkeypatch.setattr(
        module.filesystem,
        "validate_target_identity",
        lambda *args, **kwargs: (11, 22),
    )
    monkeypatch.setattr(
        module.filesystem,
        "runtime_identity_evidence",
        lambda *args, **kwargs: {
            "root_st_dev": 11,
            "root_st_ino": 22,
            "marker_st_dev": 11,
            "marker_st_ino": 23,
            "marker_st_size": 42,
            "marker_st_ctime_ns": 99,
            "marker_sha256": "1" * 64,
        },
    )
    monkeypatch.setattr(
        module._BoundNfsTarget,
        "_composition_sha256",
        lambda self: "2" * 64,
    )

    def inspect_state(root, obj, *, target_runtime_identity_sha256):
        del root
        calls.append("inspect_state")
        return DestinationInspection(
            target_runtime_identity_sha256=target_runtime_identity_sha256,
            target_id=obj.target_id,
            object_kind=obj.object_kind,
            relative_uri=obj.relative_uri,
            expected_byte_size=obj.expected_byte_size,
            expected_sha256=obj.expected_sha256,
            final_state="absent",
            transient_state="clean",
            destination_witness_sha256="3" * 64,
            transient_witness_sha256="4" * 64,
        )

    monkeypatch.setattr(module.inspection, "inspect_destination_state", inspect_state)
    monkeypatch.setattr(
        module.inspection,
        "cleanup_owned_partial_existing",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("read-only inspection invoked cleanup")
        ),
    )

    bound = NfsTarget(Path("/replica")).bind("backup", "1" * 64)
    witness = bound.runtime_identity_witness_sha256()
    result = bound.inspect_state(_obj())
    assert len(witness) == 64
    assert witness == witness.lower()
    assert result.target_runtime_identity_sha256 == witness
    assert result.final_state == "absent"
    assert result.transient_state == "clean"
    assert calls == ["inspect_state"]
    assert "replica" not in witness


def test_bound_target_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.replication.adapters.nfs import target as module

    monkeypatch.setattr(
        module.filesystem,
        "validate_target_identity",
        lambda *args, **kwargs: (11, 22),
    )
    bound = NfsTarget(Path("/replica")).bind("backup", "1" * 64)
    with pytest.raises(ReplicationError) as exc:
        bound.inspect_state(_obj(target_id="other"))
    assert (exc.value.code, exc.value.finding) == (4, "target_identity_mismatch")
