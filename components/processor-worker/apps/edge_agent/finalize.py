"""Pure finalization logic for the ``edge-agent finalize-file`` command.

Pure module: it validates inputs, derives content-addressed spool paths, builds
the ``artifact-manifest.v1`` mapping, and serializes deterministic JSON. It does
NOT touch the filesystem, spawn ffprobe, hash real bytes, or copy media; those
effectful steps live in ``cli.py`` behind tool/existence guards, mirroring the simulator
``profile.py`` / ``cli.py`` split.

Finalization contract:
- Finalize exactly ONE already-generated bounded 10 s recording per invocation.
- Artifact identity is ``sha256:<hex>`` of the finalized media bytes only.
- The manifest emits ONLY the declared ``artifact-manifest.v1`` fields. No
  session, sequence, capture-interval, media-profile, duration, or
  ffprobe-validation field is added; authoritative session/sequence/capture
  persistence is deferred to registration.
- Manifest ``finalized_at`` is the computed ``capture_ended_at`` (capture start +
  ffprobe-observed duration).
- The exact frozen manifest shape is validated at RUNTIME with the standard
  library (``validate_manifest_shape``); JSON Schema validation is retained in the
  test suite. No schema change and no new contract or dependency is introduced.
- Deterministic JSON: UTF-8, sorted keys, two-space indent, ``\n`` newlines,
  exactly one trailing newline.
- ``source.v1`` and the deterministic-media descriptor are fully validated
  (required fields, enums, unknown fields, expected profile/duration/frame count)
  before any media is copied. Input bytes are never modified.
- No receipt, completion marker, filesystem ledger, SQLite row, or outbox event
  is created here. SQLite authority begins during registration.

This module is standard-library only. ffprobe is an external prerequisite
verified by ``cli.py`` and the finalization executable acceptance.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# ── locked finalization constants ───────────────────────────────────────────
MANIFEST_CONTRACT = "artifact-manifest.v1"
MANIFEST_SCHEMA_VERSION = 1
ARTIFACT_KIND = "raw_media"          # a finalized simulator recording
MEDIA_TYPE = "video/mp4"
DIGEST_ALGORITHM = "sha256"
MEDIA_SUFFIX = ".mp4"
MANIFEST_SUFFIX = ".json"
PARTIAL_SUFFIX = ".partial"

# Locked SPEC-002 profile the finalized media must still satisfy. ffprobe evidence
# (cli.py) must prove all of these; mirrored here for a stdlib-only expectation.
EXPECTED_CODEC = "h264"
EXPECTED_WIDTH = 1280
EXPECTED_HEIGHT = 720
EXPECTED_FRAME_RATE_RATIONAL = "15/1"
EXPECTED_FRAME_RATE = 15
EXPECTED_DURATION_SECONDS = 10          # SPEC-003 finalizes one bounded 10 s recording
EXPECTED_FRAME_COUNT = 150              # 10 s x 15 fps, exact decoded frames
DURATION_TOLERANCE_MS = 100

# Remaining locked SPEC-002 profile fields the descriptor must declare exactly
# (mirrored from apps/camera_simulator/profile.py at baseline c80cea5).
PROFILE_ENCODER = "libx264"
PROFILE_PIXEL_FORMAT = "yuv420p"
PROFILE_SYNTHETIC_SOURCE = "testsrc2"
PROFILE_AUDIO = False
PROFILE_GOP_FRAMES = 15
PROFILE_FASTSTART = True
PROFILE_CREATION_TIME = "1970-01-01T00:00:00Z"

# A deterministic-media descriptor must carry a deterministic source identity,
# even though the general frozen source.v1 schema also permits rtsp/import kinds.
DESCRIPTOR_SOURCE_KIND = "deterministic"

# Frozen contract constraints mirrored for stdlib-only validation; the schemas
# themselves are NOT modified.
_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ARTIFACT_ID_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_RFC3339_UTC_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$"
)

# Frozen source.v1 enums (mirrored from schemas/source.v1.schema.json).
_SOURCE_KINDS = ("deterministic", "rtsp", "recording_import")
_CLOCK_DOMAINS = ("source", "system", "unknown")
_SOURCE_REQUIRED = ("schema_version", "source_id", "source_kind", "display_name", "clock_domain")
_SOURCE_ALLOWED = set(_SOURCE_REQUIRED)

# Frozen artifact-manifest.v1 shape (mirrored from the schema for a stdlib-only
# runtime shape check; JSON Schema validation is retained in tests).
_MANIFEST_REQUIRED = (
    "schema_version", "artifact_id", "source_id", "artifact_kind",
    "media_type", "byte_size", "digest", "storage_uri", "finalized_at",
)
_MANIFEST_ALLOWED = set(_MANIFEST_REQUIRED) | {"parent_artifact_id"}
_ARTIFACT_KINDS = ("raw_media", "derived_media", "metadata")

# SPEC-002 deterministic-media descriptor shape (mirrored from
# apps/camera_simulator/profile.py; the descriptor is a non-contract receipt).
MEDIA_DESCRIPTOR_KIND = "deterministic-media-descriptor.v1"
_DESCRIPTOR_REQUIRED_TOP = ("descriptor_kind", "source", "profile", "requested", "expected", "observed")
_DESCRIPTOR_ALLOWED_TOP = set(_DESCRIPTOR_REQUIRED_TOP)
_PROFILE_ALLOWED = {
    "width", "height", "frame_rate", "frame_rate_rational", "codec_name",
    "encoder", "pixel_format", "synthetic_source", "audio", "gop_frames",
    "faststart", "creation_time",
}
_REQUESTED_ALLOWED = {"duration_seconds"}
_EXPECTED_ALLOWED = {
    "width", "height", "codec_name", "avg_frame_rate", "duration_seconds",
    "duration_tolerance_ms", "frame_count",
}

# Spool sub-trees (all beneath one caller-provided spool root, one filesystem).
PARTIAL_DIR = "partial"
COMPLETE_DIR = "complete"
MANIFESTS_DIR = "manifests"
SHA256_DIR = "sha256"


class FinalizeError(Exception):
    """A clean, user-facing error carrying a CLI exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


# ── strict type predicates (Python's bool is an int subclass; distinguish it) ─
def _is_int(value: Any) -> bool:
    return type(value) is int  # rejects bool, which would pass isinstance(int)


def _is_bool(value: Any) -> bool:
    return type(value) is bool


@dataclass(frozen=True)
class FinalizeRequest:
    """Fully-resolved inputs for finalizing one recording."""

    input_media_path: str
    input_descriptor_path: str
    spool_root: str
    session_id: str
    sequence: int
    capture_started_at: str


# ── validation (raise FinalizeError with the documented exit code) ───────────
def validate_session_id(session_id: str) -> None:
    # Reuse the source_id grammar: a stable, path-safe token.
    if not _SOURCE_ID_PATTERN.match(session_id):
        raise FinalizeError(
            "session-id must match ^[a-z0-9][a-z0-9._-]{0,127}$ "
            f"(got {session_id!r})",
            code=2,
        )


def validate_sequence(sequence: int) -> None:
    if not _is_int(sequence):
        raise FinalizeError("sequence must be an integer", code=2)
    if sequence <= 0:
        raise FinalizeError(f"sequence must be a positive integer (got {sequence})", code=2)


def validate_rfc3339_utc(value: str, field: str) -> datetime:
    """Parse an RFC3339 UTC ``date-time``; accept both ``Z`` and ``+00:00`` inputs.

    Both canonical UTC spellings are accepted on input; naive, non-UTC-offset, and
    other shapes are rejected. Emission is always canonical ``Z`` (see
    ``capture_ended_at``), so stored/contract timestamps stay stable.
    """
    if not isinstance(value, str) or not _RFC3339_UTC_PATTERN.match(value):
        raise FinalizeError(
            f"{field} must be RFC3339 UTC (e.g. 2026-08-04T10:00:00Z or ...+00:00): {value!r}",
            code=2,
        )
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise FinalizeError(f"{field} is not a valid timestamp: {value!r}", code=2) from exc
    return parsed


def _validate_source_v1(source: Any) -> dict[str, Any]:
    """Fully validate an embedded source.v1 block against the frozen constraints."""
    if not isinstance(source, dict):
        raise FinalizeError("descriptor is missing a source.v1 identity block", code=2)
    unknown = set(source) - _SOURCE_ALLOWED
    if unknown:
        raise FinalizeError(f"descriptor source has unknown fields: {sorted(unknown)}", code=2)
    for field in _SOURCE_REQUIRED:
        if field not in source:
            raise FinalizeError(f"descriptor source missing required field: {field}", code=2)
    if not (_is_int(source["schema_version"]) and source["schema_version"] == 1):
        raise FinalizeError("descriptor source.schema_version must be integer 1", code=2)
    source_id = source["source_id"]
    if not isinstance(source_id, str) or not _SOURCE_ID_PATTERN.match(source_id):
        raise FinalizeError("descriptor source.source_id is missing or invalid", code=2)
    if source["source_kind"] not in _SOURCE_KINDS:
        raise FinalizeError(f"descriptor source.source_kind must be one of {_SOURCE_KINDS}", code=2)
    display_name = source["display_name"]
    if not isinstance(display_name, str) or not (1 <= len(display_name) <= 200):
        raise FinalizeError("descriptor source.display_name length must be 1-200", code=2)
    if source["clock_domain"] not in _CLOCK_DOMAINS:
        raise FinalizeError(f"descriptor source.clock_domain must be one of {_CLOCK_DOMAINS}", code=2)
    return source


def validate_descriptor(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Fully validate the deterministic-media descriptor; return source.v1.

    Enforces the real descriptor shape written by ``camera-simulator``:
    - exact allowed/required top-level fields;
    - ``descriptor_kind == deterministic-media-descriptor.v1``;
    - complete embedded ``source.v1``;
    - locked ``profile`` (width/height/codec/fps/pixel format/synthetic source);
    - ``requested.duration_seconds == 10``;
    - complete ``expected`` block, including ``duration_tolerance_ms == 100``;
    - ``observed`` is present and an object, but its volatile contents are NOT
      treated as invariant;
    - unknown top-level and invariant-section fields are rejected.

    Input bytes are never modified.
    """
    if not isinstance(descriptor, dict):
        raise FinalizeError("descriptor must be a JSON object", code=2)

    unknown_top = set(descriptor) - _DESCRIPTOR_ALLOWED_TOP
    if unknown_top:
        raise FinalizeError(f"descriptor has unknown top-level fields: {sorted(unknown_top)}", code=2)
    for field in _DESCRIPTOR_REQUIRED_TOP:
        if field not in descriptor:
            raise FinalizeError(f"descriptor missing required field: {field}", code=2)

    if descriptor["descriptor_kind"] != MEDIA_DESCRIPTOR_KIND:
        raise FinalizeError(
            f"descriptor_kind must be {MEDIA_DESCRIPTOR_KIND!r} "
            f"(got {descriptor['descriptor_kind']!r})",
            code=2,
        )

    source = _validate_source_v1(descriptor["source"])
    # A deterministic-media descriptor must be a deterministic source, even though
    # the general source.v1 schema also permits rtsp/recording_import identities.
    if source["source_kind"] != DESCRIPTOR_SOURCE_KIND:
        raise FinalizeError(
            f"descriptor source.source_kind must be {DESCRIPTOR_SOURCE_KIND!r} for a "
            f"deterministic-media descriptor (got {source['source_kind']!r})",
            code=2,
        )
    _validate_descriptor_profile(descriptor["profile"])
    _validate_descriptor_requested(descriptor["requested"])
    _validate_descriptor_expected(descriptor["expected"])

    if not isinstance(descriptor["observed"], dict):
        raise FinalizeError("descriptor 'observed' must be an object", code=2)
    # 'observed' is intentionally NOT validated further: its contents (paths,
    # argv, probe) legitimately vary per run and are not part of the invariant.

    return source


def _validate_descriptor_profile(profile: Any) -> None:
    if not isinstance(profile, dict):
        raise FinalizeError("descriptor 'profile' must be an object", code=2)
    unknown = set(profile) - _PROFILE_ALLOWED
    if unknown:
        raise FinalizeError(f"descriptor profile has unknown fields: {sorted(unknown)}", code=2)
    # Every locked profile field must be present with the intended exact TYPE and
    # value. Integer fields reject booleans; the two boolean flags require bool.
    int_fields = {
        "width": EXPECTED_WIDTH,
        "height": EXPECTED_HEIGHT,
        "frame_rate": EXPECTED_FRAME_RATE,
        "gop_frames": PROFILE_GOP_FRAMES,
    }
    str_fields = {
        "codec_name": EXPECTED_CODEC,
        "frame_rate_rational": EXPECTED_FRAME_RATE_RATIONAL,
        "encoder": PROFILE_ENCODER,
        "pixel_format": PROFILE_PIXEL_FORMAT,
        "synthetic_source": PROFILE_SYNTHETIC_SOURCE,
        "creation_time": PROFILE_CREATION_TIME,
    }
    bool_fields = {"audio": PROFILE_AUDIO, "faststart": PROFILE_FASTSTART}

    for field in (*int_fields, *str_fields, *bool_fields):
        if field not in profile:
            raise FinalizeError(f"descriptor profile missing field: {field}", code=2)

    problems: list[str] = []
    for key, want in int_fields.items():
        if not (_is_int(profile[key]) and profile[key] == want):
            problems.append(f"{key}={profile[key]!r} != int {want!r}")
    for key, want in str_fields.items():
        if not (isinstance(profile[key], str) and profile[key] == want):
            problems.append(f"{key}={profile[key]!r} != {want!r}")
    for key, want in bool_fields.items():
        if not (_is_bool(profile[key]) and profile[key] == want):
            problems.append(f"{key}={profile[key]!r} != bool {want!r}")
    if problems:
        raise FinalizeError("descriptor profile mismatch: " + "; ".join(problems), code=2)


def _validate_descriptor_requested(requested: Any) -> None:
    if not isinstance(requested, dict):
        raise FinalizeError("descriptor 'requested' must be an object", code=2)
    unknown = set(requested) - _REQUESTED_ALLOWED
    if unknown:
        raise FinalizeError(f"descriptor requested has unknown fields: {sorted(unknown)}", code=2)
    if not (_is_int(requested.get("duration_seconds")) and requested["duration_seconds"] == EXPECTED_DURATION_SECONDS):
        raise FinalizeError(
            f"descriptor requested.duration_seconds must be integer {EXPECTED_DURATION_SECONDS} "
            f"(got {requested.get('duration_seconds')!r})",
            code=2,
        )


def _validate_descriptor_expected(expected: Any) -> None:
    if not isinstance(expected, dict):
        raise FinalizeError("descriptor 'expected' must be an object", code=2)
    unknown = set(expected) - _EXPECTED_ALLOWED
    if unknown:
        raise FinalizeError(f"descriptor expected has unknown fields: {sorted(unknown)}", code=2)
    for field in _EXPECTED_ALLOWED:
        if field not in expected:
            raise FinalizeError(f"descriptor expected missing field: {field}", code=2)
    int_checks = {
        "width": EXPECTED_WIDTH,
        "height": EXPECTED_HEIGHT,
        "duration_seconds": EXPECTED_DURATION_SECONDS,
        "duration_tolerance_ms": DURATION_TOLERANCE_MS,
        "frame_count": EXPECTED_FRAME_COUNT,
    }
    str_checks = {
        "codec_name": EXPECTED_CODEC,
        "avg_frame_rate": EXPECTED_FRAME_RATE_RATIONAL,
    }
    problems: list[str] = []
    for key, want in int_checks.items():
        if not (_is_int(expected[key]) and expected[key] == want):
            problems.append(f"{key}={expected[key]!r} != int {want!r}")
    for key, want in str_checks.items():
        if not (isinstance(expected[key], str) and expected[key] == want):
            problems.append(f"{key}={expected[key]!r} != {want!r}")
    if problems:
        raise FinalizeError("descriptor expected mismatch: " + "; ".join(problems), code=2)


def validate_request(request: FinalizeRequest) -> None:
    validate_session_id(request.session_id)
    validate_sequence(request.sequence)
    started = validate_rfc3339_utc(request.capture_started_at, "capture-started-at")
    # Prove the end instant (start + the locked 10 s) is representable BEFORE any
    # spool or staging media is created, so an unrepresentable timestamp fails
    # early with no filesystem output.
    try:
        started + timedelta(seconds=EXPECTED_DURATION_SECONDS)
    except (OverflowError, ValueError, OSError) as exc:
        raise FinalizeError(
            f"capture-started-at + {EXPECTED_DURATION_SECONDS}s is unrepresentable: "
            f"{request.capture_started_at!r}",
            code=2,
        ) from exc


# ── runtime manifest-shape validation (stdlib only; JSON Schema stays in tests) ─
def validate_manifest_shape(manifest: dict[str, Any]) -> None:
    """Assert the EXACT frozen artifact-manifest.v1 shape without any dependency.

    Mirrors schemas/artifact-manifest.v1.schema.json: required fields present, no
    unknown fields, patterns/enums/types enforced. JSON Schema validation is
    retained in the test suite; this is the runtime guard that ships.
    """
    if not isinstance(manifest, dict):
        raise FinalizeError("manifest must be a JSON object", code=6)
    unknown = set(manifest) - _MANIFEST_ALLOWED
    if unknown:
        raise FinalizeError(f"manifest has unknown fields: {sorted(unknown)}", code=6)
    for field in _MANIFEST_REQUIRED:
        if field not in manifest:
            raise FinalizeError(f"manifest missing required field: {field}", code=6)
    if not (_is_int(manifest["schema_version"]) and manifest["schema_version"] == 1):
        raise FinalizeError("manifest schema_version must be integer 1", code=6)
    if not (isinstance(manifest["artifact_id"], str) and _ARTIFACT_ID_PATTERN.match(manifest["artifact_id"])):
        raise FinalizeError("manifest artifact_id must match ^sha256:[a-f0-9]{64}$", code=6)
    if not (isinstance(manifest["source_id"], str) and _SOURCE_ID_PATTERN.match(manifest["source_id"])):
        raise FinalizeError("manifest source_id is invalid", code=6)
    if manifest["artifact_kind"] not in _ARTIFACT_KINDS:
        raise FinalizeError(f"manifest artifact_kind must be one of {_ARTIFACT_KINDS}", code=6)
    media_type = manifest["media_type"]
    if not (isinstance(media_type, str) and 1 <= len(media_type) <= 255):
        raise FinalizeError("manifest media_type length must be 1-255", code=6)
    byte_size = manifest["byte_size"]
    if not (_is_int(byte_size) and byte_size >= 0):
        raise FinalizeError("manifest byte_size must be a non-negative integer", code=6)
    digest = manifest["digest"]
    if not isinstance(digest, dict) or set(digest) != {"algorithm", "value"}:
        raise FinalizeError("manifest digest must have exactly algorithm and value", code=6)
    if digest["algorithm"] != "sha256" or not (
        isinstance(digest["value"], str) and _SHA256_PATTERN.match(digest["value"])
    ):
        raise FinalizeError("manifest digest must be sha256 with 64 hex chars", code=6)
    if not (isinstance(manifest["storage_uri"], str) and len(manifest["storage_uri"]) >= 1):
        raise FinalizeError("manifest storage_uri must be a non-empty string", code=6)
    finalized_at = manifest["finalized_at"]
    try:
        validate_rfc3339_utc(finalized_at, "manifest finalized_at")
    except FinalizeError as exc:
        # This is a generated-manifest contract failure, not bad CLI input.
        raise FinalizeError("manifest finalized_at must be RFC3339 UTC", code=6) from exc
    if "parent_artifact_id" in manifest:
        parent = manifest["parent_artifact_id"]
        if not (isinstance(parent, str) and _ARTIFACT_ID_PATTERN.match(parent)):
            raise FinalizeError("manifest parent_artifact_id must match ^sha256:[a-f0-9]{64}$", code=6)


# ── content-addressed path derivation (pure; POSIX-style spool-relative) ─────
def _shard(sha256_hex: str) -> str:
    return sha256_hex[:2]


def media_relative_path(sha256_hex: str) -> str:
    """Spool-relative content-addressed media path (stable, no host prefix)."""
    return f"{COMPLETE_DIR}/{SHA256_DIR}/{_shard(sha256_hex)}/{sha256_hex}{MEDIA_SUFFIX}"


def manifest_relative_path(sha256_hex: str) -> str:
    """Spool-relative content-addressed manifest path (stable, no host prefix)."""
    return f"{MANIFESTS_DIR}/{SHA256_DIR}/{_shard(sha256_hex)}/{sha256_hex}{MANIFEST_SUFFIX}"


def partial_relative_path(source_id: str, session_id: str, sequence: int) -> str:
    """Spool-relative media staging path (per source/session/sequence)."""
    return f"{PARTIAL_DIR}/{source_id}/{session_id}/{sequence}{MEDIA_SUFFIX}{PARTIAL_SUFFIX}"


def storage_uri(sha256_hex: str) -> str:
    """Stable ``file:`` URI for the manifest ``storage_uri`` field.

    Deliberately spool-relative: contract fields must not embed the caller's
    absolute host spool root or other unstable invocation data.
    """
    return f"file:{media_relative_path(sha256_hex)}"


# ── manifest assembly + deterministic serialization ─────────────────────────
def capture_ended_at(capture_started_at: str, duration_seconds: float) -> str:
    """capture_ended_at = capture start + observed duration, canonical RFC3339 Z.

    Uses checked ``timedelta`` arithmetic (not raw Unix-timestamp float math) and
    converts any overflow/out-of-range/non-finite failure into a FinalizeError so
    an unrepresentable end instant never escapes as a traceback.
    """
    started = validate_rfc3339_utc(capture_started_at, "capture-started-at")
    duration = float(duration_seconds)
    if not math.isfinite(duration) or duration < 0:
        raise FinalizeError(f"observed duration is not a finite, non-negative value: {duration_seconds!r}", code=6)
    try:
        ended = started + timedelta(seconds=duration)
    except (OverflowError, ValueError, OSError) as exc:
        raise FinalizeError(f"capture end instant is unrepresentable: {exc}", code=2) from exc
    return ended.isoformat().replace("+00:00", "Z")


def build_manifest(
    *,
    source_id: str,
    sha256_hex: str,
    byte_size: int,
    finalized_at: str,
) -> dict[str, Any]:
    """Assemble the frozen ``artifact-manifest.v1`` mapping (no extra fields).

    Only the schema-required/allowed fields are emitted; the finalizer adds no
    fields the frozen contract does not define.
    """
    if not _SHA256_PATTERN.match(sha256_hex):
        raise FinalizeError("media sha256 is not 64 lowercase hex chars", code=6)
    if not (_is_int(byte_size) and byte_size >= 0):
        raise FinalizeError("byte_size must be a non-negative integer", code=6)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_id": f"sha256:{sha256_hex}",
        "source_id": source_id,
        "artifact_kind": ARTIFACT_KIND,
        "media_type": MEDIA_TYPE,
        "byte_size": byte_size,
        "digest": {"algorithm": DIGEST_ALGORITHM, "value": sha256_hex},
        "storage_uri": storage_uri(sha256_hex),
        "finalized_at": finalized_at,
    }
    # Guarantee the built manifest matches the exact frozen shape before it ships.
    validate_manifest_shape(manifest)
    return manifest


def serialize_manifest(manifest: dict[str, Any]) -> bytes:
    """Deterministic manifest bytes: sorted keys, 2-space indent, one trailing \\n."""
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")
