"""Shared edge-agent verification helpers for finalization and registration.

Behavior-preserving extraction of the filesystem-safety, ffprobe-profile, and
media-hash checks that finalization already performs, so
registration reuses the SAME verification instead of a divergent copy (the registration contract requires reuse and behavior-preserving extraction, not duplication).

Standard-library only. ``ffprobe`` is an external prerequisite. Errors are raised
as ``FinalizeError`` with the finalization exit codes; registration callers translate the
evidence-gate codes at their boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from apps.edge_agent import finalize
from apps.edge_agent.finalize import FinalizeError

_COPY_CHUNK = 1024 * 1024


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise FinalizeError(f"{name} not found on PATH; it is a required prerequisite", code=3)


def exists_or_symlink(path: Path, label: str) -> bool:
    """True if the path exists or is a (possibly broken) symlink; clean error on I/O."""
    try:
        return path.exists() or path.is_symlink()
    except OSError as exc:
        raise FinalizeError(f"could not check {label} destination {path}: {exc}", code=5) from exc


def require_within_spool(spool_root: Path, target: Path, label: str) -> None:
    """Reject symlink-based or resolved-path escapes from the spool root.

    Checks every existing path component from the spool root down to the target
    for symlinks, then confirms the resolved target still lives beneath the
    resolved spool root. Identical to the finalization safety check.
    """
    try:
        real_root = spool_root.resolve(strict=True)
    except OSError as exc:
        raise FinalizeError(f"spool root is not accessible: {exc}", code=5) from exc

    try:
        rel = target.relative_to(spool_root)
    except ValueError:
        raise FinalizeError(f"{label} is not under the spool root: {target}", code=5)

    probe = spool_root
    for part in rel.parts:
        probe = probe / part
        if probe.is_symlink():
            raise FinalizeError(f"{label} path crosses a symlink (refusing): {probe}", code=4)

    existing = spool_root
    for part in rel.parts:
        candidate = existing / part
        if not candidate.exists():
            break
        existing = candidate
    resolved_existing = existing.resolve()
    if resolved_existing != real_root and real_root not in resolved_existing.parents:
        raise FinalizeError(f"{label} escapes the spool root: {target}", code=5)


def hash_file(path: Path, label: str) -> tuple[str, int]:
    """Return (sha256_hex, byte_size) of a file, streamed. Clean error on I/O."""
    hasher = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_COPY_CHUNK)
                if not chunk:
                    break
                hasher.update(chunk)
                total += len(chunk)
    except OSError as exc:
        raise FinalizeError(f"{label} read failed: {exc}", code=6) from exc
    return hasher.hexdigest(), total


def ffprobe_duration_seconds(media_path: Path) -> float:
    """Run ffprobe; assert the locked deterministic media profile; return observed duration.

    Byte-for-byte the finalization profile proof: h264, 1280x720, avg_frame_rate 15/1,
    exactly 150 decoded frames, 10 s +/-100 ms.
    """
    argv = [
        "ffprobe",
        "-v", "error",
        "-count_frames",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,nb_read_frames:format=duration",
        "-of", "json",
        str(media_path),
    ]
    try:
        completed = subprocess.run(
            argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit code {exc.returncode}"
        raise FinalizeError(f"ffprobe failed: {tail}", code=6) from exc
    except OSError as exc:
        raise FinalizeError(f"ffprobe could not start: {exc}", code=6) from exc

    try:
        probe = json.loads(completed.stdout)
        stream = probe["streams"][0]
        codec = stream["codec_name"]
        width = int(stream["width"])
        height = int(stream["height"])
        avg_rate = stream["avg_frame_rate"]
        frames = int(stream["nb_read_frames"])
        duration_s = float(probe["format"]["duration"])
    except (json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError) as exc:
        raise FinalizeError(f"ffprobe output not understood: {exc}", code=6) from exc

    problems: list[str] = []
    if codec != finalize.EXPECTED_CODEC:
        problems.append(f"codec {codec!r} != {finalize.EXPECTED_CODEC!r}")
    if (width, height) != (finalize.EXPECTED_WIDTH, finalize.EXPECTED_HEIGHT):
        problems.append(
            f"size {width}x{height} != {finalize.EXPECTED_WIDTH}x{finalize.EXPECTED_HEIGHT}"
        )
    if avg_rate != finalize.EXPECTED_FRAME_RATE_RATIONAL:
        problems.append(f"avg_frame_rate {avg_rate!r} != {finalize.EXPECTED_FRAME_RATE_RATIONAL!r}")
    if frames != finalize.EXPECTED_FRAME_COUNT:
        problems.append(f"decoded frames {frames} != {finalize.EXPECTED_FRAME_COUNT}")
    observed_ms = duration_s * 1000
    target_ms = finalize.EXPECTED_DURATION_SECONDS * 1000
    if abs(observed_ms - target_ms) > finalize.DURATION_TOLERANCE_MS:
        problems.append(
            f"duration {observed_ms:.0f}ms outside {target_ms}ms "
            f"+/-{finalize.DURATION_TOLERANCE_MS}ms"
        )
    if problems:
        raise FinalizeError("finalized media failed profile check: " + "; ".join(problems), code=6)
    return duration_s


def interval_is_locked_ten_seconds(started_at: str, ended_at: str) -> bool:
    """True iff ended-started is 10 s +/-100 ms and start precedes end.

    Uses the finalize RFC3339 parser so both ...Z and ...+00:00 are accepted.
    """
    start = finalize.validate_rfc3339_utc(started_at, "capture-started-at")
    end = finalize.validate_rfc3339_utc(ended_at, "manifest finalized_at")
    if end < start:
        return False
    delta_ms = (end - start).total_seconds() * 1000
    target_ms = finalize.EXPECTED_DURATION_SECONDS * 1000
    return abs(delta_ms - target_ms) <= finalize.DURATION_TOLERANCE_MS


def verify_media_and_manifest(
    *,
    sha256_hex: str,
    media_path: Path,
    manifest_bytes: bytes,
    capture_started_at: str,
    run_ffprobe: bool = True,
) -> tuple[dict, str, int, str]:
    """The substantive evidence proof shared by registration AND crash recovery.

    Verifies a CANDIDATE media path + EXACT manifest bytes (works on either an
    occurrence partial before publication OR a published final). Proves:
      - deterministic artifact-manifest.v1 bytes (byte-identical to canonical);
      - exact frozen manifest shape;
      - recomputed media sha256/size vs artifact-id/filename/digest/byte_size;
      - exact raw-media subtype (raw_media, video/mp4, no parent_artifact_id);
      - content-addressed storage_uri;
      - canonical RFC3339 finalized_at;
      - the locked 10 s ±100 ms interval vs capture_started_at;
      - (when ``run_ffprobe``) the real H.264/1280x720/15fps/150-frame/10 s profile.

    Returns (manifest, media_hash, media_size, manifest_sha256). Every failure is
    raised as ``FinalizeError(code=6)`` so callers keep the exit-6 evidence code.
    All arguments are already-read/derived; this performs media hashing + ffprobe
    but no path-safety checks (callers own those against their spool context).
    """
    # deterministic manifest bytes
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizeError(f"manifest is not valid UTF-8 JSON: {exc}", code=6) from exc
    finalize.validate_manifest_shape(manifest)  # raises FinalizeError(code=6)
    if manifest_bytes != finalize.serialize_manifest(manifest):
        raise FinalizeError(
            "manifest bytes are not the deterministic artifact-manifest.v1 serialization",
            code=6,
        )

    # recomputed media identity vs every declared value
    media_hash, media_size = hash_file(media_path, "candidate media")
    if media_hash != sha256_hex:
        raise FinalizeError("recomputed media sha256 disagrees with expected hash", code=6)
    if manifest["artifact_id"] != f"sha256:{sha256_hex}":
        raise FinalizeError("manifest artifact_id disagrees with expected hash", code=6)
    if manifest["digest"]["value"] != media_hash:
        raise FinalizeError("manifest digest disagrees with recomputed media hash", code=6)
    if manifest["byte_size"] != media_size:
        raise FinalizeError("manifest byte_size disagrees with recomputed media size", code=6)

    # exact SPEC-003 subtype + content-addressed facts
    if manifest["storage_uri"] != finalize.storage_uri(sha256_hex):
        raise FinalizeError("manifest storage_uri is not the content-addressed media URI", code=6)
    if manifest["artifact_kind"] != finalize.ARTIFACT_KIND:
        raise FinalizeError(f"manifest artifact_kind must be {finalize.ARTIFACT_KIND!r}", code=6)
    if manifest["media_type"] != finalize.MEDIA_TYPE:
        raise FinalizeError(f"manifest media_type must be {finalize.MEDIA_TYPE!r}", code=6)
    if "parent_artifact_id" in manifest:
        raise FinalizeError("SPEC-003 raw media must not declare parent_artifact_id", code=6)

    finalized = finalize.validate_rfc3339_utc(manifest["finalized_at"], "manifest finalized_at")
    if finalized.isoformat().replace("+00:00", "Z") != manifest["finalized_at"]:
        raise FinalizeError("manifest finalized_at is not canonical RFC3339 UTC", code=6)

    # locked interval vs the durable/declared capture start
    if not interval_is_locked_ten_seconds(capture_started_at, manifest["finalized_at"]):
        raise FinalizeError(
            "capture start -> manifest finalized_at is not the locked 10 s +/-100 ms interval",
            code=6,
        )

    # real media profile
    if run_ffprobe:
        require_tool("ffprobe")
        ffprobe_duration_seconds(media_path)

    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    return manifest, media_hash, media_size, manifest_sha
