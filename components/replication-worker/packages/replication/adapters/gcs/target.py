"""Google Cloud Storage target adapter for provider-neutral replication."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud import storage
from google.cloud.storage import exceptions as storage_exceptions

from packages.agent_contracts.canonical import canonical_sha256
from packages.replication.contracts.model import ReplicaObject, ReplicationError
from packages.replication.contracts.target import (
    DestinationInspection,
    DestinationState,
    PublishResult,
    TargetCompositionProjection,
)
from packages.replication.core.source import source_path

from .model import (
    ADAPTER_KIND,
    canonical_marker_bytes,
    marker_name,
    marker_sha256 as expected_marker_sha256,
    normalize_prefix,
    object_name,
)

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class _BlobEvidence:
    generation: int
    metageneration: int
    byte_size: int
    content_sha256: str


def _target_unavailable(exc: Exception) -> ReplicationError:
    return ReplicationError("target_unavailable", code=5)


def _read_error(exc: Exception, *, missing: str, precondition: str) -> ReplicationError:
    if isinstance(exc, gexc.NotFound):
        return ReplicationError(missing, code=6 if missing.startswith("destination_") else 4)
    if isinstance(exc, gexc.PreconditionFailed):
        identity_or_collision = precondition in {
            "destination_collision",
            "target_identity_mismatch",
            "transient_state_present",
        }
        return ReplicationError(precondition, code=4 if identity_or_collision else 6)
    if isinstance(
        exc,
        (
            gexc.Forbidden,
            gexc.Unauthorized,
            gexc.TooManyRequests,
            gexc.ServiceUnavailable,
            gexc.GatewayTimeout,
            gexc.DeadlineExceeded,
        ),
    ):
        return _target_unavailable(exc)
    if isinstance(exc, (storage_exceptions.DataCorruption, storage_exceptions.InvalidResponse)):
        return ReplicationError("target_io_error", code=5)
    if isinstance(exc, gexc.GoogleAPICallError):
        return ReplicationError("target_io_error", code=5)
    raise exc


def _write_error(exc: Exception) -> ReplicationError:
    if isinstance(exc, (gexc.Forbidden, gexc.Unauthorized)):
        return ReplicationError("target_read_only", code=5)
    if isinstance(
        exc,
        (
            gexc.NotFound,
            gexc.TooManyRequests,
            gexc.ServiceUnavailable,
            gexc.GatewayTimeout,
            gexc.DeadlineExceeded,
        ),
    ):
        return _target_unavailable(exc)
    if isinstance(exc, (storage_exceptions.DataCorruption, storage_exceptions.InvalidResponse)):
        return ReplicationError("target_io_error", code=5)
    if isinstance(exc, gexc.GoogleAPICallError):
        return ReplicationError("target_io_error", code=5)
    raise exc


def _require_bucket(bucket: Any) -> None:
    try:
        bucket.reload()
    except Exception as exc:
        raise _target_unavailable(exc) from exc


def _metadata(blob: Any) -> tuple[int, int, int]:
    try:
        generation = int(blob.generation)
        metageneration = int(getattr(blob, "metageneration", 0))
        byte_size = int(blob.size)
    except (TypeError, ValueError) as exc:
        raise ReplicationError("target_io_error", code=5) from exc
    if generation <= 0 or metageneration < 0 or byte_size < 0:
        raise ReplicationError("target_io_error", code=5)
    return generation, metageneration, byte_size


def _download_hash(blob: Any, *, generation: int, missing: str, changed: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    try:
        with tempfile.SpooledTemporaryFile(max_size=8 * _CHUNK, mode="w+b") as handle:
            blob.download_to_file(
                handle,
                if_generation_match=generation,
                checksum="auto",
            )
            handle.seek(0)
            while True:
                chunk = handle.read(_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
    except Exception as exc:
        raise _read_error(exc, missing=missing, precondition=changed) from exc
    return total, digest.hexdigest()


def _read_blob_evidence(blob: Any, *, missing: str, changed: str) -> _BlobEvidence:
    try:
        blob.reload()
        before = _metadata(blob)
    except Exception as exc:
        if isinstance(exc, ReplicationError):
            raise
        raise _read_error(exc, missing=missing, precondition=changed) from exc
    total, digest = _download_hash(
        blob,
        generation=before[0],
        missing=missing,
        changed=changed,
    )
    try:
        blob.reload(if_generation_match=before[0])
        after = _metadata(blob)
    except Exception as exc:
        if isinstance(exc, ReplicationError):
            raise
        raise _read_error(exc, missing=missing, precondition=changed) from exc
    if before != after or total != before[2]:
        raise ReplicationError(changed, code=4 if changed in {"destination_collision", "target_identity_mismatch"} else 6)
    return _BlobEvidence(
        generation=before[0],
        metageneration=before[1],
        byte_size=before[2],
        content_sha256=digest,
    )


@dataclass(frozen=True)
class _BoundGcsTarget:
    bucket: Any = field(repr=False)
    bucket_name: str
    prefix: str
    target_id: str
    marker_sha256: str
    marker_generation: int
    marker_metageneration: int
    adapter_kind: str = ADAPTER_KIND

    def _marker_blob(self) -> Any:
        return self.bucket.blob(marker_name(self.prefix))

    def _marker_evidence(self) -> _BlobEvidence:
        _require_bucket(self.bucket)
        evidence = _read_blob_evidence(
            self._marker_blob(),
            missing="target_identity_mismatch",
            changed="target_identity_mismatch",
        )
        canonical = canonical_marker_bytes(self.target_id)
        if (
            evidence.generation != self.marker_generation
            or evidence.metageneration != self.marker_metageneration
            or evidence.byte_size != len(canonical)
            or evidence.content_sha256 != self.marker_sha256
        ):
            raise ReplicationError("target_identity_mismatch", code=4)
        return evidence

    def validate_identity(self) -> None:
        self._marker_evidence()

    def runtime_identity_witness_sha256(self) -> str:
        evidence = self._marker_evidence()
        composition_sha256 = TargetCompositionProjection(
            target_id=self.target_id,
            adapter_kind=self.adapter_kind,
            location={
                "bucket_name": self.bucket_name,
                "prefix": self.prefix,
            },
        ).sha256
        adapter_witness_sha256 = canonical_sha256(
            {
                "schema": "replication-gcs-runtime-identity.v1",
                "bucket_name": self.bucket_name,
                "prefix": self.prefix,
                "marker_object_name": marker_name(self.prefix),
                "marker_generation": evidence.generation,
                "marker_metageneration": evidence.metageneration,
                "marker_sha256": evidence.content_sha256,
            }
        )
        return canonical_sha256(
            {
                "schema": "replication-runtime-target-identity.v1",
                "adapter_kind": self.adapter_kind,
                "target_id": self.target_id,
                "marker_sha256": self.marker_sha256,
                "target_composition_sha256": composition_sha256,
                "adapter_runtime_witness_sha256": adapter_witness_sha256,
            }
        )

    def cleanup_transient(self, obj: ReplicaObject) -> bool:
        del obj
        return False

    def _blob(self, obj: ReplicaObject) -> Any:
        return self.bucket.blob(object_name(self.prefix, obj))

    def inspect_state(self, obj: ReplicaObject) -> DestinationInspection:
        if obj.target_id != self.target_id:
            raise ReplicationError("target_identity_mismatch", code=4)
        runtime_witness = self.runtime_identity_witness_sha256()
        name = object_name(self.prefix, obj)
        blob = self.bucket.blob(name)
        try:
            evidence = _read_blob_evidence(
                blob,
                missing="destination_missing",
                changed="destination_collision",
            )
        except ReplicationError as exc:
            if exc.finding == "destination_missing":
                final_state = "absent"
                destination_witness_sha256 = canonical_sha256(
                    {
                        "schema": "replication-gcs-destination-witness.v1",
                        "target_runtime_identity_sha256": runtime_witness,
                        "object_name": name,
                        "state": "absent",
                    }
                )
            else:
                raise
        else:
            if (
                evidence.byte_size != obj.expected_byte_size
                or evidence.content_sha256 != obj.expected_sha256
            ):
                raise ReplicationError("destination_collision", code=4)
            final_state = "exact"
            destination_witness_sha256 = canonical_sha256(
                {
                    "schema": "replication-gcs-destination-witness.v1",
                    "target_runtime_identity_sha256": runtime_witness,
                    "object_name": name,
                    "state": "exact",
                    "generation": evidence.generation,
                    "metageneration": evidence.metageneration,
                    "byte_size": evidence.byte_size,
                    "content_sha256": evidence.content_sha256,
                }
            )

        transient_witness_sha256 = canonical_sha256(
            {
                "schema": "replication-gcs-transient-witness.v1",
                "target_runtime_identity_sha256": runtime_witness,
                "object_name": name,
                "state": "clean",
                "mechanism": "not-applicable",
            }
        )
        if self.runtime_identity_witness_sha256() != runtime_witness:
            raise ReplicationError("target_identity_mismatch", code=4)
        return DestinationInspection(
            target_runtime_identity_sha256=runtime_witness,
            target_id=obj.target_id,
            object_kind=obj.object_kind,
            relative_uri=obj.relative_uri,
            expected_byte_size=obj.expected_byte_size,
            expected_sha256=obj.expected_sha256,
            final_state=final_state,  # type: ignore[arg-type]
            transient_state="clean",
            destination_witness_sha256=destination_witness_sha256,
            transient_witness_sha256=transient_witness_sha256,
        )

    def inspect(self, obj: ReplicaObject) -> DestinationState:
        blob = self._blob(obj)
        try:
            evidence = _read_blob_evidence(
                blob,
                missing="destination_missing",
                changed="destination_collision",
            )
        except ReplicationError as exc:
            if exc.finding == "destination_missing":
                return "absent"
            raise
        if (
            evidence.byte_size == obj.expected_byte_size
            and evidence.content_sha256 == obj.expected_sha256
        ):
            return "exact"
        raise ReplicationError("destination_collision", code=4)

    def publish_immutable(self, spool_root: Path, obj: ReplicaObject) -> PublishResult:
        source = source_path(spool_root, obj.relative_uri)
        blob = self._blob(obj)
        try:
            with source.open("rb") as handle:
                blob.upload_from_file(
                    handle,
                    rewind=True,
                    size=obj.expected_byte_size,
                    content_type="application/octet-stream",
                    if_generation_match=0,
                    checksum="auto",
                )
        except gexc.PreconditionFailed:
            if self.inspect(obj) == "exact":
                return "adopted"
            raise ReplicationError("destination_collision", code=4)
        except Exception as exc:
            raise _write_error(exc) from exc
        self.verify(obj)
        return "published"

    def verify(self, obj: ReplicaObject) -> None:
        evidence = _read_blob_evidence(
            self._blob(obj),
            missing="destination_missing",
            changed="destination_digest_mismatch",
        )
        if evidence.byte_size != obj.expected_byte_size:
            raise ReplicationError("destination_size_mismatch", code=6)
        if evidence.content_sha256 != obj.expected_sha256:
            raise ReplicationError("destination_digest_mismatch", code=6)


@dataclass(frozen=True)
class GcsTarget:
    """GCS target using external ADC only when a provider operation is requested."""

    bucket_name: str
    prefix: str = ""
    client: Any | None = field(default=None, compare=False, repr=False)
    adapter_kind: str = ADAPTER_KIND

    def __post_init__(self) -> None:
        if not isinstance(self.bucket_name, str) or not self.bucket_name:
            raise ReplicationError("target_config_invalid", code=2)
        object.__setattr__(self, "prefix", normalize_prefix(self.prefix))

    def _client(self) -> Any:
        return self.client if self.client is not None else storage.Client()

    def _bucket(self) -> Any:
        return self._client().bucket(self.bucket_name)

    def initialize(self, target_id: str) -> str:
        bucket = self._bucket()
        _require_bucket(bucket)
        canonical = canonical_marker_bytes(target_id)
        expected = expected_marker_sha256(target_id)
        blob = bucket.blob(marker_name(self.prefix))
        try:
            blob.upload_from_string(
                canonical,
                content_type="application/json",
                if_generation_match=0,
                checksum="auto",
            )
        except gexc.PreconditionFailed:
            pass
        except Exception as exc:
            raise _write_error(exc) from exc

        evidence = _read_blob_evidence(
            blob,
            missing="target_identity_mismatch",
            changed="target_identity_mismatch",
        )
        if evidence.byte_size != len(canonical) or evidence.content_sha256 != expected:
            raise ReplicationError("target_identity_mismatch", code=4)
        return expected

    def bind(self, target_id: str, marker_sha256: str) -> _BoundGcsTarget:
        bucket = self._bucket()
        _require_bucket(bucket)
        if marker_sha256 != expected_marker_sha256(target_id):
            raise ReplicationError("target_identity_mismatch", code=4)
        blob = bucket.blob(marker_name(self.prefix))
        evidence = _read_blob_evidence(
            blob,
            missing="target_identity_mismatch",
            changed="target_identity_mismatch",
        )
        canonical = canonical_marker_bytes(target_id)
        if evidence.byte_size != len(canonical) or evidence.content_sha256 != marker_sha256:
            raise ReplicationError("target_identity_mismatch", code=4)
        return _BoundGcsTarget(
            bucket=bucket,
            bucket_name=self.bucket_name,
            prefix=self.prefix,
            target_id=target_id,
            marker_sha256=marker_sha256,
            marker_generation=evidence.generation,
            marker_metageneration=evidence.metageneration,
        )
