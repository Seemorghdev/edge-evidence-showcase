"""Registration logic for ``edge-agent register-finalized``.

Pure identity + event planning for turning an already-published finalized artifact
into durable SQLite authority: one ``artifacts`` row, one ``capture_occurrences``
row, and one ``SegmentFinalized`` ``outbox_events`` row, committed in a single
transaction by ``cli.py``.

Pure/effect split (mirrors ``finalize.py`` / ``cli.py``):
- This module is pure, standard-library only: exact deterministic identities,
  the frozen ``segment-finalized.v1`` event, deterministic payload bytes + their
  SHA-256, and ``plan_registration`` (all values derived from inputs).
- The single SQLite transaction, PRAGMAs, evidence gate, and disposition output
  live in ``cli.py``. Database wall-clock stamps (``recorded_at`` /
  ``completed_at`` / ``created_at``) are produced by SQLite defaults, NOT by this
  module, per the canonical spec.

Canonical registration identities (frozen; do not derive a namespace or use
pipe-delimited names):

    occurrence_id = uuid5(NAMESPACE_URL,
        "https://schemas.seemorgh.dev/edge-evidence/occurrences/v1/"
        "<source_id>/<session_id>/<sequence>")
    event_id      = uuid5(NAMESPACE_URL,
        "https://schemas.seemorgh.dev/edge-evidence/events/segment-finalized/v1/"
        "<occurrence_id>")

``occurred_at = capture_ended_at`` (the manifest's ``finalized_at``).
``manifest_uri = file:manifests/sha256/<xx>/<sha>.json``.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from apps.edge_agent.finalize import (
    _SOURCE_ID_PATTERN,
    FinalizeError,
    validate_manifest_shape,
    validate_rfc3339_utc,
    validate_sequence,
    validate_session_id,
)

# ── frozen event constants (segment-finalized.v1) ────────────────────────────
EVENT_TYPE = "SegmentFinalized"
EVENT_SCHEMA_VERSION = 1
AGGREGATE_TYPE = "capture_occurrence"

# ── canonical UUIDv5 URI bases (frozen) ──────────────────────────────────────
_OCCURRENCE_URI_BASE = "https://schemas.seemorgh.dev/edge-evidence/occurrences/v1/"
_EVENT_URI_BASE = "https://schemas.seemorgh.dev/edge-evidence/events/segment-finalized/v1/"

_ARTIFACT_ID_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class RegisterError(FinalizeError):
    """A clean, user-facing registration error carrying a CLI exit code.

    Subclasses FinalizeError so the CLI's single ``except FinalizeError`` handler
    (and its ``.code`` contract) covers registration failures unchanged.
    """


@dataclass(frozen=True)
class RegisterRequest:
    """Fully-resolved inputs for registering one finalized artifact."""

    database_path: str
    spool_root: str
    artifact_id: str
    session_id: str
    sequence: int
    capture_started_at: str


# ── deterministic identities (exact canonical URIs) ──────────────────────────
def occurrence_uri_name(source_id: str, session_id: str, sequence: int) -> str:
    return f"{_OCCURRENCE_URI_BASE}{source_id}/{session_id}/{sequence}"


def occurrence_id(source_id: str, session_id: str, sequence: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, occurrence_uri_name(source_id, session_id, sequence)))


def event_uri_name(occurrence_uuid: str) -> str:
    return f"{_EVENT_URI_BASE}{occurrence_uuid}"


def event_id(occurrence_uuid: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, event_uri_name(occurrence_uuid)))


def manifest_uri_for(sha256_hex: str) -> str:
    """``file:manifests/sha256/<xx>/<sha>.json`` (spool-relative, no host prefix)."""
    return f"file:manifests/sha256/{sha256_hex[:2]}/{sha256_hex}.json"


# ── validation ───────────────────────────────────────────────────────────────
def validate_request(request: RegisterRequest) -> None:
    if not _ARTIFACT_ID_PATTERN.match(request.artifact_id):
        raise RegisterError("--artifact-id must match ^sha256:[a-f0-9]{64}$", code=2)
    validate_session_id(request.session_id)
    validate_sequence(request.sequence)
    if request.sequence <= 0:
        raise RegisterError("--sequence must be a positive integer", code=2)
    validate_rfc3339_utc(request.capture_started_at, "capture-started-at")


def canonical_rfc3339_utc(value: str, field: str) -> str:
    """Return an accepted UTC timestamp in the one stored ``...Z`` spelling."""
    parsed = validate_rfc3339_utc(value, field)
    return parsed.isoformat().replace("+00:00", "Z")


def validate_registered_manifest(manifest: Any) -> dict[str, Any]:
    """Re-validate the on-disk manifest against the frozen artifact-manifest shape.

    Any shape failure is an evidence/verification failure (the caller handed us a
    manifest that is not a valid finalized artifact). Mapped to exit 6 by cli.py.
    """
    if not isinstance(manifest, dict):
        raise RegisterError("manifest must be a JSON object", code=6)
    try:
        validate_manifest_shape(manifest)  # frozen SPEC-003 runtime shape check
    except FinalizeError as exc:
        raise RegisterError(f"manifest is not a valid artifact-manifest.v1: {exc}", code=6) from exc
    return manifest


# ── event assembly + deterministic serialization ─────────────────────────────
def build_segment_finalized_event(
    *,
    event_uuid: str,
    occurred_at: str,
    source_id: str,
    sequence: int,
    interval_started_at: str,
    interval_ended_at: str,
    artifact_id: str,
    manifest_uri: str,
) -> dict[str, Any]:
    """Assemble the exact frozen ``segment-finalized.v1`` event mapping."""
    if not _ARTIFACT_ID_PATTERN.match(artifact_id):
        raise RegisterError("event artifact_id must match ^sha256:[a-f0-9]{64}$", code=6)
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": event_uuid,
        "event_type": EVENT_TYPE,
        "occurred_at": occurred_at,
        "source_id": source_id,
        "sequence_number": sequence,
        "interval": {
            "started_at": interval_started_at,
            "ended_at": interval_ended_at,
        },
        "artifact_id": artifact_id,
        "manifest_uri": manifest_uri,
    }


# frozen segment-finalized.v1 runtime shape (stdlib; JSON Schema stays in tests)
_EVENT_REQUIRED = (
    "schema_version", "event_id", "event_type", "occurred_at", "source_id",
    "sequence_number", "interval", "artifact_id", "manifest_uri",
)
_EVENT_ALLOWED = set(_EVENT_REQUIRED)
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def validate_event_shape(event: Any) -> None:
    """Assert the EXACT frozen segment-finalized.v1 shape (stdlib runtime guard)."""
    if not isinstance(event, dict):
        raise RegisterError("event must be a JSON object", code=6)
    unknown = set(event) - _EVENT_ALLOWED
    if unknown:
        raise RegisterError(f"event has unknown fields: {sorted(unknown)}", code=6)
    for field in _EVENT_REQUIRED:
        if field not in event:
            raise RegisterError(f"event missing required field: {field}", code=6)
    if type(event["schema_version"]) is not int or event["schema_version"] != 1:
        raise RegisterError("event schema_version must be 1", code=6)
    if not (isinstance(event["event_id"], str) and _UUID_PATTERN.match(event["event_id"])):
        raise RegisterError("event event_id must be a UUID string", code=6)
    if event["event_type"] != EVENT_TYPE:
        raise RegisterError("event event_type must be 'SegmentFinalized'", code=6)
    validate_rfc3339_utc(event["occurred_at"], "event occurred_at")
    if not (isinstance(event["source_id"], str) and _SOURCE_ID_PATTERN.match(event["source_id"])):
        raise RegisterError("event source_id is invalid", code=6)
    seq = event["sequence_number"]
    if type(seq) is not int or seq < 0:
        raise RegisterError("event sequence_number must be a non-negative integer", code=6)
    interval = event["interval"]
    if not isinstance(interval, dict) or set(interval) != {"started_at", "ended_at"}:
        raise RegisterError("event interval must have exactly started_at and ended_at", code=6)
    validate_rfc3339_utc(interval["started_at"], "event interval.started_at")
    validate_rfc3339_utc(interval["ended_at"], "event interval.ended_at")
    if not (isinstance(event["artifact_id"], str) and _ARTIFACT_ID_PATTERN.match(event["artifact_id"])):
        raise RegisterError("event artifact_id must match ^sha256:[a-f0-9]{64}$", code=6)
    if not (isinstance(event["manifest_uri"], str) and len(event["manifest_uri"]) >= 1):
        raise RegisterError("event manifest_uri must be a non-empty string", code=6)


def serialize_payload(event: dict[str, Any]) -> bytes:
    """Deterministic payload bytes: UTF-8, sorted keys, 2-space indent, one \\n.

    Matches the frozen manifest serialization style; ``payload_sha256`` is the
    SHA-256 of exactly these bytes. Compact JSON is NOT compliant.
    """
    text = json.dumps(event, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def payload_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ── the pure registration plan ───────────────────────────────────────────────
@dataclass(frozen=True)
class RegistrationPlan:
    """Every deterministic value for one registration (no wall-clock stamps).

    SQLite produces recorded_at / completed_at / created_at via column defaults.
    """

    # artifacts row
    artifact_id: str
    source_id: str
    artifact_kind: str
    media_type: str
    byte_size: int
    digest_algorithm: str
    digest_value: str
    storage_uri: str
    manifest_uri: str
    manifest_sha256: str
    finalized_at: str
    # capture_occurrences row
    occurrence_id: str
    session_id: str
    sequence_number: int
    capture_started_at: str
    capture_ended_at: str
    # outbox_events row
    event_id: str
    event_payload: bytes
    event_payload_sha256: str


def plan_registration(
    *,
    request: RegisterRequest,
    manifest: dict[str, Any],
    media_sha256_hex: str,
    manifest_sha256_hex: str,
) -> RegistrationPlan:
    """Pure: derive every identity, row value, and event for one registration.

    The caller (cli.py) has already run the full evidence gate (ffprobe, recomputed
    media hash + size, recomputed manifest bytes hash) and passes the verified
    hashes in. This function performs NO I/O.
    """
    manifest = validate_registered_manifest(manifest)
    source_id = manifest["source_id"]
    artifact_id = manifest["artifact_id"]
    digest_value = manifest["digest"]["value"]

    interval_started_at = canonical_rfc3339_utc(
        request.capture_started_at, "capture-started-at"
    )
    interval_ended_at = manifest["finalized_at"]

    occ = occurrence_id(source_id, request.session_id, request.sequence)
    evt = event_id(occ)
    muri = manifest_uri_for(media_sha256_hex)
    occurred_at = interval_ended_at

    event = build_segment_finalized_event(
        event_uuid=evt,
        occurred_at=occurred_at,
        source_id=source_id,
        sequence=request.sequence,
        interval_started_at=interval_started_at,
        interval_ended_at=interval_ended_at,
        artifact_id=artifact_id,
        manifest_uri=muri,
    )
    validate_event_shape(event)
    payload = serialize_payload(event)

    return RegistrationPlan(
        artifact_id=artifact_id,
        source_id=source_id,
        artifact_kind=manifest["artifact_kind"],
        media_type=manifest["media_type"],
        byte_size=manifest["byte_size"],
        digest_algorithm=manifest["digest"]["algorithm"],
        digest_value=digest_value,
        storage_uri=manifest["storage_uri"],
        manifest_uri=muri,
        manifest_sha256=manifest_sha256_hex,
        finalized_at=manifest["finalized_at"],
        occurrence_id=occ,
        session_id=request.session_id,
        sequence_number=request.sequence,
        capture_started_at=interval_started_at,
        capture_ended_at=interval_ended_at,
        event_id=evt,
        event_payload=payload,
        event_payload_sha256=payload_sha256(payload),
    )
