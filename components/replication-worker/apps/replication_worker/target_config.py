"""Non-secret target composition for the replication-worker application boundary."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePath

from packages.replication.adapters.nfs.target import NfsTarget
from packages.replication.contracts.model import ReplicationError, validate_target_id
from packages.replication.contracts.target import (
    ReplicationTarget,
    ReplicationTargetFactory,
    TargetCompositionProjection,
)


_NFS_KEYS = frozenset({"adapter_kind", "target_id", "target_root"})
_GCS_KEYS = frozenset({"adapter_kind", "target_id", "bucket_name", "prefix"})


@dataclass(frozen=True)
class _NfsTargetFactory:
    composition: TargetCompositionProjection

    def fresh(self) -> ReplicationTarget:
        return NfsTarget(Path(self.composition.location["root_realpath"]))


@dataclass(frozen=True)
class _GcsTargetFactory:
    composition: TargetCompositionProjection

    def fresh(self) -> ReplicationTarget:
        return _gcs_target(
            self.composition.location["bucket_name"],
            self.composition.location["prefix"],
        )


@dataclass(frozen=True)
class TargetSelection:
    target_id: str
    composition: TargetCompositionProjection
    factory: ReplicationTargetFactory

    @property
    def target(self) -> ReplicationTarget:
        """Compatibility projection returning a fresh target for each access."""

        return self.factory.fresh()


def _invalid() -> ReplicationError:
    return ReplicationError("target_config_invalid", code=2)


def _read(path: Path) -> dict[str, object]:
    try:
        with Path(path).open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise _invalid() from exc
    if not isinstance(raw, dict):
        raise _invalid()
    return raw


def _require_exact_strings(
    raw: dict[str, object],
    expected: frozenset[str],
) -> dict[str, str]:
    if set(raw) != expected:
        raise _invalid()
    if any(type(raw[key]) is not str for key in expected):
        raise _invalid()
    return {key: str(raw[key]) for key in expected}


def _canonical_nfs_root(value: str) -> str:
    if not value or "\x00" in value:
        raise _invalid()
    path = Path(value)
    if not path.is_absolute():
        raise _invalid()
    if any(part in {".", ".."} for part in PurePath(value).parts):
        raise _invalid()
    try:
        if path.is_symlink() or not path.is_dir():
            raise _invalid()
        return path.resolve(strict=True).as_posix()
    except OSError as exc:
        raise _invalid() from exc


def _canonical_gcs_prefix(value: str) -> str:
    """Normalize the provider-neutral prefix without importing the GCS package."""

    if value == "":
        return ""
    if value.startswith("/") or value.endswith("/") or "\\" in value:
        raise _invalid()
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise _invalid()
    return value


def _gcs_target(bucket_name: str, prefix: str) -> ReplicationTarget:
    try:
        from packages.replication.adapters.gcs.target import GcsTarget
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing == "google" or missing.startswith("google."):
            raise ReplicationError("target_adapter_unavailable", code=2) from exc
        raise
    return GcsTarget(bucket_name, prefix)


def load_target_config(path: Path) -> TargetSelection:
    raw = _read(path)
    adapter_kind = raw.get("adapter_kind")
    if adapter_kind == "mounted_nfs_v4":
        config = _require_exact_strings(raw, _NFS_KEYS)
        target_id = validate_target_id(config["target_id"])
        composition = TargetCompositionProjection(
            target_id=target_id,
            adapter_kind="mounted_nfs_v4",
            location={"root_realpath": _canonical_nfs_root(config["target_root"])},
        )
        factory = _NfsTargetFactory(composition)
        return TargetSelection(
            target_id=target_id,
            composition=composition,
            factory=factory,
        )

    if adapter_kind == "gcs":
        config = _require_exact_strings(raw, _GCS_KEYS)
        target_id = validate_target_id(config["target_id"])
        if not config["bucket_name"]:
            raise _invalid()
        prefix = _canonical_gcs_prefix(config["prefix"])
        composition = TargetCompositionProjection(
            target_id=target_id,
            adapter_kind="gcs",
            location={
                "bucket_name": config["bucket_name"],
                "prefix": prefix,
            },
        )
        factory = _GcsTargetFactory(composition)
        return TargetSelection(
            target_id=target_id,
            composition=composition,
            factory=factory,
        )

    raise _invalid()
