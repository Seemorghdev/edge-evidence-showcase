"""Occurrence-addressed staging, publication, quarantine, and crash barriers.

Effectful filesystem layer for the orchestrated (``finalize-and-register``) and
``reconcile`` paths. Reuses finalization publication semantics (media-first,
manifest-last, atomic no-replace, directory-fsync) and the shared verification
module. Standard-library only.

Crash barriers: a module-level registry of no-op callbacks. Production keeps them
no-op; a test-only child helper overrides one to signal its parent (which sends a
real ``SIGKILL``) at the named point. Barriers never change production behavior.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable

from apps.edge_agent import finalize, verification
from apps.edge_agent.finalize import FinalizeError
from apps.edge_agent.register import RegisterError

_COPY_CHUNK = 1024 * 1024

# ── crash barriers (production default: no-op) ───────────────────────────────
BARRIERS = (
    "after_intent_commit",
    "during_media_copy",
    "after_manifest_partial_fsync",
    "after_media_publish",
    "after_manifest_publish",
    "after_database_writes_before_commit",
    "after_complete_commit_before_output",
)
_hooks: dict[str, Callable[[], None]] = {name: (lambda: None) for name in BARRIERS}


def set_barrier(name: str, callback: Callable[[], None]) -> None:
    """Test-only: install a barrier callback. Unknown names raise (guards typos)."""
    if name not in _hooks:
        raise KeyError(f"unknown crash barrier: {name}")
    _hooks[name] = callback


def reset_barriers() -> None:
    for name in BARRIERS:
        _hooks[name] = lambda: None


def barrier(name: str) -> None:
    """Invoke the barrier hook (no-op in production)."""
    _hooks[name]()


# ── occurrence-addressed staging paths ───────────────────────────────────────
def occurrence_media_partial(spool_root: Path, source_id: str, session_id: str,
                             sequence: int) -> Path:
    return spool_root / "partial" / source_id / session_id / f"{sequence}.mp4.partial"


def occurrence_manifest_partial(spool_root: Path, source_id: str, session_id: str,
                                sequence: int) -> Path:
    return spool_root / "partial" / source_id / session_id / f"{sequence}.manifest.json.partial"


def quarantine_media(spool_root: Path, occurrence_id: str) -> Path:
    return spool_root / "quarantine" / occurrence_id / "media.mp4.partial"


def quarantine_manifest(spool_root: Path, occurrence_id: str) -> Path:
    return spool_root / "quarantine" / occurrence_id / "manifest.json.partial"


# ── low-level durable primitives (mirror SPEC-003 cli.py) ────────────────────
def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as exc:
        raise RegisterError(f"could not open directory for fsync {path}: {exc}", code=5) from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise RegisterError(f"directory fsync failed {path}: {exc}", code=5) from exc
    finally:
        os.close(fd)


def copy_hash_fsync(
    src: Path,
    staging: Path,
    *,
    mid_copy_barrier: str | Callable[[], None] | None = None,
) -> tuple[str, int]:
    """Exclusively create ``staging``, copy ``src`` into it while hashing, fsync.

    If ``mid_copy_barrier`` is set, fire it after the first non-empty chunk is
    durably written (barrier ``during_media_copy``). Returns (sha256, byte_size).
    """
    hasher = hashlib.sha256()
    total = 0
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(staging, flags, 0o644)
    except FileExistsError as exc:
        raise RegisterError(f"occurrence media partial already exists: {staging}", code=4) from exc
    except OSError as exc:
        raise RegisterError(f"could not create occurrence media partial {staging}: {exc}", code=5) from exc
    fired = False
    try:
        with os.fdopen(fd, "wb") as out, src.open("rb") as inp:
            while True:
                chunk = inp.read(_COPY_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                total += len(chunk)
                if mid_copy_barrier and not fired and total > 0:
                    out.flush()
                    os.fsync(out.fileno())
                    fired = True
                    if callable(mid_copy_barrier):
                        mid_copy_barrier()
                    else:
                        barrier(mid_copy_barrier)  # test-only SIGKILL point
            out.flush()
            os.fsync(out.fileno())
    except OSError as exc:
        raise RegisterError(f"copy to occurrence media partial failed: {exc}", code=5) from exc
    return hasher.hexdigest(), total


def write_manifest_partial(staging: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(staging, flags, 0o644)
    except FileExistsError as exc:
        raise RegisterError(f"occurrence manifest partial already exists: {staging}", code=4) from exc
    except OSError as exc:
        raise RegisterError(f"could not create occurrence manifest partial {staging}: {exc}", code=5) from exc
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
    except OSError as exc:
        raise RegisterError(f"occurrence manifest partial write failed: {exc}", code=5) from exc


def _guard_within_spool(spool_root: Path, target: Path, label: str) -> None:
    """Reject symlink/resolved-path escapes for a staging/final/quarantine path."""
    try:
        verification.require_within_spool(spool_root, target, label)
    except FinalizeError as exc:
        raise RegisterError(f"{label} path check failed: {exc}", code=5) from exc
    if target.is_symlink():
        raise RegisterError(f"{label} is a symlink (refusing): {target}", code=5)


def _reject_symlinked_ancestors(spool_root: Path, target: Path, label: str) -> None:
    """Reject a symlink anywhere from ``spool_root`` down to ``target``'s parent.

    ``_guard_within_spool`` proves the resolved path stays within the spool and the
    leaf is not itself a symlink, but a NON-mutating preflight must also refuse a
    symlinked ANCESTOR directory before any existence check, read, or write follows
    a link out of the spool subtree. Missing ancestors are fine (they will be
    created as real directories); only an existing symlink component is rejected.
    """
    try:
        rel = target.relative_to(spool_root)
    except ValueError as exc:
        raise RegisterError(f"{label} escapes the spool root: {target}", code=5) from exc
    probe = spool_root
    for part in rel.parts[:-1]:  # every ancestor up to (not including) the leaf
        probe = probe / part
        if probe.is_symlink():
            raise RegisterError(
                f"{label} has a symlinked parent component (refusing): {probe}", code=5
            )


def preflight_occurrence_partials(spool_root: Path, media_partial: Path,
                                  manifest_partial: Path) -> None:
    """Non-mutating path/feasibility preflight for the occurrence partials.

    Runs BEFORE the durable PREPARED commit (frozen order:
    preflight → lock → commit PREPARED) so a path/symlink/filesystem problem can
    never leave a durable PREPARED row behind. Performs only read-only checks:
    within-spool resolution, leaf-not-symlink, no symlinked ancestor component,
    and same-filesystem feasibility. Creates nothing. Callers MUST re-run this
    under the held spool lock before the first write (TOCTOU defense within the
    documented single-node threat model).
    """
    for part, label in ((media_partial, "media partial"),
                        (manifest_partial, "manifest partial")):
        _guard_within_spool(spool_root, part, label)
        _reject_symlinked_ancestors(spool_root, part, label)
        _prove_same_filesystem(spool_root, part, label)


def _prove_same_filesystem(spool_root: Path, target: Path, label: str) -> None:
    """All staging/final/quarantine destinations must share the spool filesystem."""
    probe = target.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        root_dev = os.stat(spool_root).st_dev
        target_dev = os.stat(probe).st_dev
    except OSError as exc:
        raise RegisterError(f"could not stat {label} destination: {exc}", code=5) from exc
    if root_dev != target_dev:
        raise RegisterError(f"{label} is on a different filesystem from the spool", code=5)


def publish_no_replace(source: Path, final: Path, label: str, spool_root: Path) -> None:
    """Atomic no-replace publish via os.link + unlink (never overwrites).

    Applies within-spool/symlink/same-filesystem guards, then fsyncs BOTH the
    destination directory and the source partial's directory (the unlink must be
    durable too). A pre-existing final target raises ``_PublishCollision`` for the
    caller to resolve by verified adoption.
    """
    _guard_within_spool(spool_root, final, label)
    _prove_same_filesystem(spool_root, final, label)
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RegisterError(f"could not create final directory for {label}: {exc}", code=5) from exc
    source_dir = source.parent
    try:
        os.link(source, final)
    except FileExistsError as exc:
        raise _PublishCollision(str(final)) from exc
    except OSError as exc:
        raise RegisterError(f"{label} publish failed: {exc}", code=5) from exc
    try:
        os.unlink(source)
    except OSError as exc:
        raise RegisterError(f"{label} staging cleanup failed: {exc}", code=5) from exc
    fsync_dir(final.parent)
    if source_dir.is_dir():
        fsync_dir(source_dir)


class _PublishCollision(Exception):
    """Internal: final target already exists; caller must verify-adopt."""


def verify_media_matches(final_media: Path, sha256_hex: str, byte_size: int) -> None:
    """Adopt an existing final media object only if it is exactly expected."""
    actual_hash, actual_size = verification.hash_file(final_media, "final media")
    if actual_hash != sha256_hex or actual_size != byte_size:
        raise RegisterError(
            "existing final media does not match expected content; corruption", code=6
        )


def verify_manifest_bytes(final_manifest: Path, payload: bytes) -> None:
    """Adopt an existing final manifest only if byte-identical to the expected."""
    try:
        actual = final_manifest.read_bytes()
    except OSError as exc:
        raise RegisterError(f"final manifest re-read failed: {exc}", code=6) from exc
    if actual != payload:
        raise RegisterError(
            "existing final manifest bytes differ from expected; corruption", code=6
        )


# ── quarantine (same-filesystem atomic no-replace move; idempotent-or-conflict)
def quarantine_partial(source: Path, dest: Path, label: str, spool_root: Path) -> str:
    """Move an occurrence partial into quarantine. Returns 'moved' or 'existing'.

    Applies within-spool/symlink/same-filesystem guards. Identical existing
    destination is adopted idempotently (source removed); a differing destination
    is corruption (exit 6). Fsyncs BOTH the destination and source directories.
    Never used on final objects.
    """
    _guard_within_spool(spool_root, dest, f"quarantine {label}")
    _prove_same_filesystem(spool_root, dest, f"quarantine {label}")
    source_dir = source.parent
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RegisterError(f"could not create quarantine dir for {label}: {exc}", code=5) from exc
    if dest.is_symlink():
        raise RegisterError(f"quarantine destination is a symlink (refusing): {dest}", code=5)
    if dest.exists():
        if not _same_bytes(source, dest):
            raise RegisterError(
                f"quarantine destination already holds different {label}; corruption", code=6
            )
        try:
            source.unlink(missing_ok=True)
        except OSError as exc:
            raise RegisterError(f"could not remove redundant {label} source: {exc}", code=5) from exc
        fsync_dir(dest.parent)
        if source_dir.is_dir():
            fsync_dir(source_dir)
        return "existing"
    try:
        os.link(source, dest)
    except FileExistsError as exc:
        raise RegisterError(f"quarantine race on {label}: {dest}", code=4) from exc
    except OSError as exc:
        raise RegisterError(f"could not quarantine {label}: {exc}", code=5) from exc
    try:
        source.unlink()
    except OSError as exc:
        raise RegisterError(f"could not remove {label} source after quarantine: {exc}", code=5) from exc
    fsync_dir(dest.parent)
    if source_dir.is_dir():
        fsync_dir(source_dir)
    return "moved"


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        ah, _ = verification.hash_file(a, "quarantine source")
        bh, _ = verification.hash_file(b, "quarantine destination")
    except FinalizeError:
        return False
    return ah == bh


def _remove_and_fsync_partial(partial: Path) -> None:
    """Remove a redundant partial and fsync its directory (durable removal)."""
    parent = partial.parent
    try:
        partial.unlink(missing_ok=True)
    except OSError as exc:
        raise RegisterError(f"could not remove redundant partial {partial}: {exc}", code=5) from exc
    if parent.is_dir():
        fsync_dir(parent)
