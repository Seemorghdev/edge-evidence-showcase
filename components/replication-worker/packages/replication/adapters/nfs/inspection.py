"""Read-only/non-creating target inspection used by reconcile and verify."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from packages.agent_contracts.canonical import canonical_sha256
from packages.replication.contracts.target import DestinationInspection

from .filesystem import (
    StableFileEvidence,
    _target_error,
    fsync_directory,
    hash_regular,
    stable_hash_regular,
    validate_root,
)
from .model import ReplicaObject, ReplicationError, canonical_file_uri, owned_partial_name


def _existing_final(target_root: Path, obj: ReplicaObject) -> Path | None:
    root = validate_root(target_root, target=True)
    relative = canonical_file_uri(obj.relative_uri)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        try:
            st = current.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _target_error(exc) from exc
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise ReplicationError("destination_path_unsafe", code=2)
    return root.joinpath(*relative.parts)


def _evidence_matches_path(path: Path, evidence: StableFileEvidence) -> bool:
    try:
        current = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _target_error(exc) from exc
    return (
        stat.S_ISREG(current.st_mode)
        and int(current.st_dev) == evidence.st_dev
        and int(current.st_ino) == evidence.st_ino
        and int(current.st_size) == evidence.st_size
        and int(current.st_mtime_ns) == evidence.st_mtime_ns
        and int(current.st_ctime_ns) == evidence.st_ctime_ns
    )


def inspect_destination_state(
    target_root: Path,
    obj: ReplicaObject,
    *,
    target_runtime_identity_sha256: str,
) -> DestinationInspection:
    """Inspect final and adapter-owned transient state without any mutation."""

    final = _existing_final(target_root, obj)
    final_evidence: StableFileEvidence | None = None
    if final is None:
        final_state = "absent"
    else:
        try:
            st = final.lstat()
        except FileNotFoundError:
            final_state = "absent"
        except OSError as exc:
            raise _target_error(exc) from exc
        else:
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise ReplicationError("destination_path_unsafe", code=2)
            final_evidence = stable_hash_regular(
                final,
                target=True,
                missing="destination_missing",
                unsafe="destination_path_unsafe",
                corrupt="destination_digest_mismatch",
                changed="destination_collision",
            )
            if (
                final_evidence.st_size != obj.expected_byte_size
                or final_evidence.content_sha256 != obj.expected_sha256
            ):
                raise ReplicationError("destination_collision", code=4)
            final_state = "exact"

    if final_state == "absent":
        destination_witness_sha256 = canonical_sha256(
            {
                "schema": "replication-nfs-destination-witness.v1",
                "target_runtime_identity_sha256": target_runtime_identity_sha256,
                "object_kind": obj.object_kind,
                "relative_uri": obj.relative_uri,
                "state": "absent",
            }
        )
    else:
        assert final_evidence is not None
        destination_witness_sha256 = canonical_sha256(
            {
                "schema": "replication-nfs-destination-witness.v1",
                "target_runtime_identity_sha256": target_runtime_identity_sha256,
                "object_kind": obj.object_kind,
                "relative_uri": obj.relative_uri,
                "state": "exact",
                "st_dev": final_evidence.st_dev,
                "st_ino": final_evidence.st_ino,
                "st_size": final_evidence.st_size,
                "st_mtime_ns": final_evidence.st_mtime_ns,
                "st_ctime_ns": final_evidence.st_ctime_ns,
                "content_sha256": final_evidence.content_sha256,
            }
        )

    partial = None if final is None else final.parent / owned_partial_name(obj)
    partial_evidence: StableFileEvidence | None = None
    if partial is None:
        transient_state = "clean"
    else:
        try:
            partial_stat = partial.lstat()
        except FileNotFoundError:
            transient_state = "clean"
        except OSError as exc:
            raise _target_error(exc) from exc
        else:
            if stat.S_ISLNK(partial_stat.st_mode) or not stat.S_ISREG(partial_stat.st_mode):
                raise ReplicationError("destination_path_unsafe", code=2)
            partial_evidence = stable_hash_regular(
                partial,
                target=True,
                missing="destination_missing",
                unsafe="destination_path_unsafe",
                corrupt="destination_digest_mismatch",
                changed="transient_state_present",
            )
            transient_state = "present"

    if transient_state == "clean":
        transient_witness_sha256 = canonical_sha256(
            {
                "schema": "replication-nfs-transient-witness.v1",
                "target_runtime_identity_sha256": target_runtime_identity_sha256,
                "object_kind": obj.object_kind,
                "relative_uri": obj.relative_uri,
                "state": "clean",
            }
        )
    else:
        assert partial_evidence is not None
        transient_witness_sha256 = canonical_sha256(
            {
                "schema": "replication-nfs-transient-witness.v1",
                "target_runtime_identity_sha256": target_runtime_identity_sha256,
                "object_kind": obj.object_kind,
                "relative_uri": obj.relative_uri,
                "state": "present",
                "st_dev": partial_evidence.st_dev,
                "st_ino": partial_evidence.st_ino,
                "st_size": partial_evidence.st_size,
                "st_mtime_ns": partial_evidence.st_mtime_ns,
                "st_ctime_ns": partial_evidence.st_ctime_ns,
                "content_sha256": partial_evidence.content_sha256,
            }
        )

    if final_state == "absent":
        current = _existing_final(target_root, obj)
        if current is not None:
            try:
                current.lstat()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise _target_error(exc) from exc
            else:
                raise ReplicationError("destination_collision", code=4)
    elif final is None or final_evidence is None or not _evidence_matches_path(final, final_evidence):
        raise ReplicationError("destination_collision", code=4)

    if transient_state == "clean" and partial is not None:
        try:
            partial.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise _target_error(exc) from exc
        else:
            raise ReplicationError("transient_state_present", code=4)
    elif transient_state == "present":
        assert partial is not None and partial_evidence is not None
        if not _evidence_matches_path(partial, partial_evidence):
            raise ReplicationError("transient_state_present", code=4)

    return DestinationInspection(
        target_runtime_identity_sha256=target_runtime_identity_sha256,
        target_id=obj.target_id,
        object_kind=obj.object_kind,
        relative_uri=obj.relative_uri,
        expected_byte_size=obj.expected_byte_size,
        expected_sha256=obj.expected_sha256,
        final_state=final_state,  # type: ignore[arg-type]
        transient_state=transient_state,  # type: ignore[arg-type]
        destination_witness_sha256=destination_witness_sha256,
        transient_witness_sha256=transient_witness_sha256,
    )


def cleanup_owned_partial_existing(target_root: Path, obj: ReplicaObject) -> bool:
    final = _existing_final(target_root, obj)
    if final is None:
        return False
    partial = final.parent / owned_partial_name(obj)
    try:
        st = partial.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _target_error(exc) from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ReplicationError("partial_cleanup_failed", code=5)
    try:
        partial.unlink()
        fsync_directory(final.parent)
    except OSError as exc:
        raise ReplicationError("partial_cleanup_failed", code=5) from exc
    return True


def reconcile_destination_state(target_root: Path, obj: ReplicaObject) -> str:
    final = _existing_final(target_root, obj)
    if final is None:
        return "absent"
    try:
        st = final.lstat()
    except FileNotFoundError:
        return "absent"
    except OSError as exc:
        raise _target_error(exc) from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ReplicationError("destination_path_unsafe", code=2)
    size, digest = hash_regular(
        final,
        target=True,
        missing="destination_missing",
        unsafe="destination_path_unsafe",
        corrupt="destination_digest_mismatch",
    )
    if size == obj.expected_byte_size and digest == obj.expected_sha256:
        return "exact"
    raise ReplicationError("destination_collision", code=4)


def verify_existing_replica(target_root: Path, obj: ReplicaObject) -> None:
    final = _existing_final(target_root, obj)
    if final is None:
        raise ReplicationError("destination_missing", code=6)
    try:
        st = final.lstat()
    except FileNotFoundError as exc:
        raise ReplicationError("destination_missing", code=6) from exc
    except OSError as exc:
        raise _target_error(exc) from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ReplicationError("destination_path_unsafe", code=2)
    size, digest = hash_regular(
        final,
        target=True,
        missing="destination_missing",
        unsafe="destination_path_unsafe",
        corrupt="destination_digest_mismatch",
    )
    if size != obj.expected_byte_size:
        raise ReplicationError("destination_size_mismatch", code=6)
    if digest != obj.expected_sha256:
        raise ReplicationError("destination_digest_mismatch", code=6)
