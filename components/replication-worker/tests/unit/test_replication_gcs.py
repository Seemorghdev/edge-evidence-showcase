"""GCS adapter contract tests without real provider credentials."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest
from google.api_core import exceptions as gexc

from packages.replication.adapters.gcs import target as target_module
from packages.replication.adapters.gcs.model import (
    canonical_marker_bytes,
    marker_name,
    marker_sha256,
    object_name,
)
from packages.replication.adapters.gcs.target import GcsTarget
from packages.replication.contracts.model import ReplicaObject, ReplicationError


@dataclass
class _Stored:
    data: bytes
    generation: int
    metageneration: int = 1


class _FakeBlob:
    def __init__(self, bucket: "_FakeBucket", name: str) -> None:
        self.bucket = bucket
        self.name = name
        self.generation: int | None = None
        self.metageneration: int | None = None
        self.size: int | None = None

    def _stored(self) -> _Stored:
        if self.name not in self.bucket.objects:
            raise gexc.NotFound("missing")
        return self.bucket.objects[self.name]

    def reload(self, if_generation_match: int | None = None) -> None:
        self.bucket.reads.append(("reload", self.name))
        stored = self._stored()
        if if_generation_match is not None and stored.generation != if_generation_match:
            raise gexc.PreconditionFailed("generation changed")
        self.generation = stored.generation
        self.metageneration = stored.metageneration
        self.size = len(stored.data)

    def upload_from_string(self, data: bytes, **kwargs) -> None:
        self.bucket.writes.append(("upload-string", self.name))
        self._create(bytes(data), kwargs.get("if_generation_match"))

    def upload_from_file(self, handle, **kwargs) -> None:
        self.bucket.writes.append(("upload-file", self.name))
        if kwargs.get("rewind"):
            handle.seek(0)
        data = handle.read()
        expected_size = kwargs.get("size")
        if expected_size is not None and len(data) != expected_size:
            raise AssertionError("fake upload size mismatch")
        self._create(data, kwargs.get("if_generation_match"))

    def _create(self, data: bytes, if_generation_match: int | None) -> None:
        if if_generation_match == 0 and self.name in self.bucket.objects:
            raise gexc.PreconditionFailed("already exists")
        generation = self.bucket.next_generation
        self.bucket.next_generation += 1
        self.bucket.objects[self.name] = _Stored(data=data, generation=generation)
        self.generation = generation
        self.metageneration = 1
        self.size = len(data)

    def download_to_file(self, handle, **kwargs) -> None:
        self.bucket.reads.append(("download", self.name))
        stored = self._stored()
        expected = kwargs.get("if_generation_match")
        if expected is not None and stored.generation != expected:
            raise gexc.PreconditionFailed("generation changed")
        handle.write(stored.data)
        if self.name in self.bucket.replace_after_download:
            self.bucket.replace_after_download.remove(self.name)
            self.bucket.objects[self.name] = _Stored(
                data=stored.data,
                generation=stored.generation + 1,
                metageneration=stored.metageneration,
            )


class _FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, _Stored] = {}
        self.next_generation = 1
        self.available = True
        self.reads: list[tuple[str, str]] = []
        self.writes: list[tuple[str, str]] = []
        self.replace_after_download: set[str] = set()

    def reload(self) -> None:
        self.reads.append(("bucket-reload", ""))
        if not self.available:
            raise gexc.NotFound("bucket missing")

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self, name)


class _FakeClient:
    def __init__(self, bucket: _FakeBucket) -> None:
        self._bucket = bucket

    def bucket(self, name: str) -> _FakeBucket:
        assert name == "spec023-test-bucket"
        return self._bucket


def _object(data: bytes = b"replica-bytes") -> ReplicaObject:
    return ReplicaObject(
        target_id="gcs-a",
        object_kind="artifact_content",
        relative_uri="file:complete/aa/object.bin",
        expected_byte_size=len(data),
        expected_sha256=hashlib.sha256(data).hexdigest(),
    )


def _target(bucket: _FakeBucket, *, prefix: str = "replicas/dev") -> GcsTarget:
    return GcsTarget(
        bucket_name="spec023-test-bucket",
        prefix=prefix,
        client=_FakeClient(bucket),
    )


def _seed_marker(bucket: _FakeBucket, *, generation: int = 10) -> str:
    bucket.objects[marker_name("replicas/dev")] = _Stored(
        data=canonical_marker_bytes("gcs-a"),
        generation=generation,
    )
    bucket.next_generation = max(bucket.next_generation, generation + 1)
    return marker_sha256("gcs-a")


def _seed_bound(bucket: _FakeBucket):
    digest = _seed_marker(bucket)
    return _target(bucket).bind("gcs-a", digest)


def test_gcs_marker_init_bind_and_exact_retry() -> None:
    bucket = _FakeBucket()
    target = _target(bucket)
    digest = target.initialize("gcs-a")
    assert target.initialize("gcs-a") == digest
    bound = target.bind("gcs-a", digest)
    bound.validate_identity()
    assert marker_name("replicas/dev") in bucket.objects


def test_gcs_publish_is_create_only_then_adopts_exact(tmp_path: Path) -> None:
    bucket = _FakeBucket()
    target = _target(bucket)
    digest = target.initialize("gcs-a")
    bound = target.bind("gcs-a", digest)
    obj = _object()
    source = tmp_path / "complete" / "aa" / "object.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"replica-bytes")

    assert bound.publish_immutable(tmp_path, obj) == "published"
    assert bound.inspect(obj) == "exact"
    bound.verify(obj)
    first = bucket.objects[object_name("replicas/dev", obj)]

    assert bound.publish_immutable(tmp_path, obj) == "adopted"
    second = bucket.objects[object_name("replicas/dev", obj)]
    assert second == first


def test_gcs_collision_never_overwrites(tmp_path: Path) -> None:
    bucket = _FakeBucket()
    target = _target(bucket)
    digest = target.initialize("gcs-a")
    bound = target.bind("gcs-a", digest)
    obj = _object()
    name = object_name("replicas/dev", obj)
    bucket.objects[name] = _Stored(data=b"wrong", generation=50)
    source = tmp_path / "complete" / "aa" / "object.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"replica-bytes")

    with pytest.raises(ReplicationError) as error:
        bound.publish_immutable(tmp_path, obj)
    assert (error.value.code, error.value.finding) == (4, "destination_collision")
    assert bucket.objects[name].data == b"wrong"


def test_independent_gcs_targets_and_bounds_have_equal_opaque_runtime_witnesses() -> None:
    bucket = _FakeBucket()
    digest = _seed_marker(bucket)
    execution_target = _target(bucket)
    verification_target = _target(bucket)
    execution = execution_target.bind("gcs-a", digest)
    verification = verification_target.bind("gcs-a", digest)

    assert execution_target is not verification_target
    assert execution is not verification
    execution_witness = execution.runtime_identity_witness_sha256()
    verification_witness = verification.runtime_identity_witness_sha256()
    assert execution_witness == verification_witness
    assert len(execution_witness) == 64
    assert execution_witness == execution_witness.lower()
    assert "bucket" not in execution_witness
    assert "replicas" not in execution_witness


def test_gcs_marker_generation_replacement_changes_runtime_identity_witness() -> None:
    bucket = _FakeBucket()
    digest = _seed_marker(bucket)
    original = _target(bucket).bind("gcs-a", digest)
    before = original.runtime_identity_witness_sha256()
    name = marker_name("replicas/dev")
    stored = bucket.objects[name]
    bucket.objects[name] = _Stored(
        data=stored.data,
        generation=stored.generation + 100,
        metageneration=stored.metageneration,
    )

    with pytest.raises(ReplicationError) as error:
        original.runtime_identity_witness_sha256()
    assert (error.value.code, error.value.finding) == (4, "target_identity_mismatch")
    replacement = _target(bucket).bind("gcs-a", digest)
    assert replacement.runtime_identity_witness_sha256() != before


def test_gcs_read_only_inspection_projects_absent_and_exact_without_mutation() -> None:
    bucket = _FakeBucket()
    bound = _seed_bound(bucket)
    obj = _object()
    before_objects = dict(bucket.objects)
    before_generation = bucket.next_generation
    before_writes = list(bucket.writes)

    absent = bound.inspect_state(obj)
    assert absent.final_state == "absent"
    assert absent.transient_state == "clean"
    assert bucket.objects == before_objects
    assert bucket.next_generation == before_generation
    assert bucket.writes == before_writes

    name = object_name("replicas/dev", obj)
    bucket.objects[name] = _Stored(data=b"replica-bytes", generation=50)
    exact_objects = dict(bucket.objects)
    exact = bound.inspect_state(obj)
    assert exact.final_state == "exact"
    assert exact.transient_state == "clean"
    assert bucket.objects == exact_objects
    assert bucket.writes == before_writes


def test_gcs_exact_byte_generation_replacement_changes_destination_witness() -> None:
    bucket = _FakeBucket()
    bound = _seed_bound(bucket)
    obj = _object()
    name = object_name("replicas/dev", obj)
    bucket.objects[name] = _Stored(data=b"replica-bytes", generation=50)
    before = bound.inspect_state(obj)
    bucket.objects[name] = _Stored(data=b"replica-bytes", generation=51)
    after = bound.inspect_state(obj)
    assert before.final_state == after.final_state == "exact"
    assert before.destination_witness_sha256 != after.destination_witness_sha256


def test_gcs_generation_change_during_hashing_fails_closed() -> None:
    bucket = _FakeBucket()
    bound = _seed_bound(bucket)
    obj = _object()
    name = object_name("replicas/dev", obj)
    bucket.objects[name] = _Stored(data=b"replica-bytes", generation=50)
    bucket.replace_after_download.add(name)
    with pytest.raises(ReplicationError) as error:
        bound.inspect_state(obj)
    assert (error.value.code, error.value.finding) == (4, "destination_collision")


def test_gcs_construction_is_lazy_and_hermetic_client_avoids_adc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        target_module.storage,
        "Client",
        lambda: (_ for _ in ()).throw(AssertionError("ADC lookup attempted")),
    )
    lazy = GcsTarget(bucket_name="spec023-test-bucket", prefix="replicas/dev")
    assert lazy.client is None

    bucket = _FakeBucket()
    bound = _seed_bound(bucket)
    assert len(bound.runtime_identity_witness_sha256()) == 64


def test_gcs_marker_replacement_invalidates_bound_identity() -> None:
    bucket = _FakeBucket()
    target = _target(bucket)
    digest = target.initialize("gcs-a")
    bound = target.bind("gcs-a", digest)
    name = marker_name("replicas/dev")
    original = bucket.objects[name]
    bucket.objects[name] = _Stored(data=original.data, generation=original.generation + 100)

    with pytest.raises(ReplicationError) as error:
        bound.validate_identity()
    assert (error.value.code, error.value.finding) == (4, "target_identity_mismatch")


def test_gcs_bucket_unavailable_is_path_neutral() -> None:
    bucket = _FakeBucket()
    target = _target(bucket)
    digest = target.initialize("gcs-a")
    bound = target.bind("gcs-a", digest)
    bucket.available = False

    with pytest.raises(ReplicationError) as error:
        bound.validate_identity()
    assert (error.value.code, error.value.finding) == (5, "target_unavailable")
    assert "spec023-test-bucket" not in str(error.value)


@pytest.mark.parametrize("prefix", ("/absolute", "trailing/", "a//b", "a/../b", "a/./b"))
def test_gcs_prefix_must_be_canonical(prefix: str) -> None:
    with pytest.raises(ReplicationError) as error:
        GcsTarget(bucket_name="spec023-test-bucket", prefix=prefix, client=_FakeClient(_FakeBucket()))
    assert (error.value.code, error.value.finding) == (2, "target_config_invalid")


def test_gcs_adapter_source_contains_no_credential_material() -> None:
    text = Path("packages/replication/adapters/gcs/target.py").read_text(encoding="utf-8").lower()
    for forbidden in (
        "google_application_credentials",
        "service_account_file",
        "service_account_info",
        "client_secret",
        "private_key",
    ):
        assert forbidden not in text
    assert "storage.client()" in text
