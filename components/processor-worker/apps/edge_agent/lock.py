"""Single-node advisory spool lock with exclusive and shared modes.

One process-scoped ``fcntl.flock`` at ``<spool-root>/.edge-agent.lock``.

- ``mode="exclusive"`` (the backward-compatible default) takes ``LOCK_EX``: held by
  ``finalize-and-register``, ``reconcile``, v3 ``register-finalized``,
  ``import-recording-window``, ``process-artifact``, and ``artifacts verify``.
- ``mode="shared"`` takes ``LOCK_SH``: held by ``capture-rtsp-window`` for its whole
  lifetime so multiple captures overlap, while maintenance/recovery stays excluded.

Shared holders coexist; an exclusive acquirer waits for all shared holders; a shared
acquirer waits for an exclusive holder. Legacy ``finalize-file`` does NOT participate.

- Waits at most five seconds for the lock, then raises exit 7.
- The lock file must be a regular, non-symlink file beneath the validated spool
  root; created mode ``0600`` with no-follow semantics where supported.
- A crash releases the kernel lock naturally (no stale-lock cleanup needed).
- No lock upgrade, downgrade, or unlock/relock within one command.

This is single-node exclusion, not a distributed lease.
"""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from apps.edge_agent.register import RegisterError

LOCK_FILENAME = ".edge-agent.lock"
_LOCK_TIMEOUT_SECONDS = 5.0
_POLL_SECONDS = 0.05
_VALID_MODES = ("exclusive", "shared")

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - platform guard
    fcntl = None  # type: ignore[assignment]


def lock_path(spool_root: Path) -> Path:
    return spool_root / LOCK_FILENAME


def _open_lock_file(spool_root: Path) -> int:
    """Open (creating if needed) a regular, non-symlink lock file mode 0600.

    Uses O_NOFOLLOW so a symlink at the lock path is refused (exit 5).
    """
    path = lock_path(spool_root)
    if path.is_symlink():
        raise RegisterError(f"lock path is a symlink (refusing): {path}", code=5)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise RegisterError(f"lock path is a symlink (refusing): {path}", code=5) from exc
        raise RegisterError(f"could not open spool lock {path}: {exc}", code=5) from exc
    # Confirm it is a regular file (not a fifo/device swapped in).
    try:
        st = os.fstat(fd)
    except OSError as exc:
        os.close(fd)
        raise RegisterError(f"could not stat spool lock {path}: {exc}", code=5) from exc
    if not _is_regular(st.st_mode):
        os.close(fd)
        raise RegisterError(f"spool lock is not a regular file: {path}", code=5)
    return fd


def _is_regular(mode: int) -> bool:
    import stat
    return stat.S_ISREG(mode)


@contextmanager
def spool_lock(
    spool_root: Path,
    mode: str = "exclusive",
) -> Iterator[None]:
    """Hold the spool lock for the duration of the block.

    ``mode`` is exactly ``"exclusive"`` (default; ``LOCK_EX``) or ``"shared"``
    (``LOCK_SH``). An invalid mode is rejected as the FIRST operation — before any
    ``fcntl`` check, spool-root check, or lock-file open — so a caller typo never
    creates or touches the lock file.

    Blocks up to five seconds; on timeout raises RegisterError(code=7). The lock is
    released and the fd closed on exit (including on error / process teardown via the
    kernel). No upgrade/downgrade/relock is performed within one call.
    """
    if mode not in _VALID_MODES:
        raise RegisterError(f"invalid spool lock mode: {mode!r}", code=7)
    if fcntl is None:  # pragma: no cover
        raise RegisterError("advisory spool lock requires POSIX fcntl", code=7)
    if not spool_root.is_dir():
        raise RegisterError(f"spool root is not a directory: {spool_root}", code=5)

    flock_op = (fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH) | fcntl.LOCK_NB
    fd = _open_lock_file(spool_root)
    acquired = False
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    try:
        while True:
            try:
                fcntl.flock(fd, flock_op)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise RegisterError(f"spool lock error: {exc}", code=7) from exc
                if time.monotonic() >= deadline:
                    raise RegisterError(
                        "could not acquire spool lock within 5 s (another operation holds it)",
                        code=7,
                    )
                time.sleep(_POLL_SECONDS)
        yield
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass  # closing the fd (and process exit) releases it regardless
        os.close(fd)