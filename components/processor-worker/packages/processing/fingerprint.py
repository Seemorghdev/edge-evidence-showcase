"""Pure processor core: canonical parameters, job identity, and the
deterministic ``artifact-fingerprint-report.v1`` document.

Standard-library only. No filesystem, no SQLite, no ffprobe. Every value here is
derived from its inputs so the same verified input + processor + contract +
canonical parameters yield one deterministic job identity and one deterministic
report byte string (and therefore one derived-artifact identity).

Frozen processor constants:
    processor_name    = artifact-fingerprint
    processor_version = 1
    output_contract   = artifact-fingerprint-report.v1
    artifact_kind     = metadata
    media_type        = application/vnd.seemorgh.artifact-fingerprint-report.v1+json
    relation_type     = derived_from

Report bytes are UTF-8, sorted keys, two-space indentation, Unix newlines, and
exactly one trailing newline (identical to finalize.serialize_manifest style).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

# ── frozen processor constants ───────────────────────────────────────────────
PROCESSOR_NAME = "artifact-fingerprint"
PROCESSOR_VERSION = "1"
OUTPUT_CONTRACT = "artifact-fingerprint-report.v1"
ARTIFACT_KIND = "metadata"
MEDIA_TYPE = "application/vnd.seemorgh.artifact-fingerprint-report.v1+json"
RELATION_TYPE = "derived_from"
REPORT_KIND = "artifact-fingerprint-report.v1"
SCHEMA_VERSION = 1

PROFILES = ("identity", "integrity")

# job_id UUIDv5 URI base (frozen; do NOT derive a namespace or use pipe-joins).
_JOB_URI_BASE = "https://schemas.seemorgh.dev/edge-evidence/processing-jobs/v1/"

_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ARTIFACT_ID_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class ProcessingError(Exception):
    """A clean, user-facing processing error carrying a CLI exit code.

    Exit codes mirror the processor command contract:
      2 invalid args/profile/identity; 6 evidence/contract/lineage/corruption.
    Filesystem (5), migration/SQLite/lock (7), missing ffprobe (3), and identity
    collision (4) are raised by the effectful orchestration layer.
    """

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def _is_int(value: Any) -> bool:
    return type(value) is int  # reject bool (an int subclass)


# ── canonical parameters ─────────────────────────────────────────────────────
def canonical_parameters(profile: str) -> bytes:
    """Exact canonical UTF-8 bytes for a profile's parameter mapping.

    The mapping is exactly ``{"profile": "<profile>"}`` serialized with the frozen
    canonical style. These exact bytes are what SQLite stores in ``parameters_json``
    and what ``parameters_sha256`` hashes.
    """
    if profile not in PROFILES:
        raise ProcessingError(f"profile must be one of {PROFILES} (got {profile!r})", code=2)
    return _canonical_bytes({"profile": profile})


def parameters_sha256(profile: str) -> str:
    return hashlib.sha256(canonical_parameters(profile)).hexdigest()


# ── job identity (UUIDv5 over the exact frozen URI) ──────────────────────────
def job_uri_name(input_digest_hex: str, params_sha256_hex: str) -> str:
    """The exact URI whose UUIDv5 is the job identity.

    ``input_digest_hex`` is the 64-hex media digest of the verified raw input
    (NOT the ``sha256:`` prefixed artifact id).
    """
    if not _SHA256_PATTERN.match(input_digest_hex):
        raise ProcessingError("input digest must be 64 lowercase hex chars", code=2)
    if not _SHA256_PATTERN.match(params_sha256_hex):
        raise ProcessingError("parameters_sha256 must be 64 lowercase hex chars", code=6)
    return (
        _JOB_URI_BASE
        + input_digest_hex
        + f"/{PROCESSOR_NAME}/{PROCESSOR_VERSION}/{OUTPUT_CONTRACT}/"
        + params_sha256_hex
    )


def job_id_for(input_digest_hex: str, profile: str) -> str:
    """UUIDv5(NAMESPACE_URL, job_uri_name(...)) as a lowercase string."""
    params_hash = parameters_sha256(profile)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, job_uri_name(input_digest_hex, params_hash)))


# ── report assembly ──────────────────────────────────────────────────────────
def build_report(
    *,
    profile: str,
    artifact_id: str,
    manifest_sha256: str,
    source_assertion: str | None = None,
    media_type: str | None = None,
    byte_size: int | None = None,
    digest_value: str | None = None,
) -> dict[str, Any]:
    """Assemble the exact frozen report mapping for a profile.

    ``identity`` uses only (artifact_id, manifest_sha256). ``integrity`` adds the
    inherited (not authenticated) source_assertion plus the frozen raw-media
    subtype facts. No path, time, environment, account, model claim, FFprobe
    output, or private field data enters the report.
    """
    if profile not in PROFILES:
        raise ProcessingError(f"profile must be one of {PROFILES} (got {profile!r})", code=2)
    if not (isinstance(artifact_id, str) and _ARTIFACT_ID_PATTERN.match(artifact_id)):
        raise ProcessingError("artifact_id must match ^sha256:[a-f0-9]{64}$", code=6)
    if not (isinstance(manifest_sha256, str) and _SHA256_PATTERN.match(manifest_sha256)):
        raise ProcessingError("manifest_sha256 must be 64 lowercase hex chars", code=6)

    common: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_kind": REPORT_KIND,
        "processor": {"name": PROCESSOR_NAME, "version": PROCESSOR_VERSION},
        "parameters": {"profile": profile},
    }

    if profile == "identity":
        report = {**common, "input": {"artifact_id": artifact_id, "manifest_sha256": manifest_sha256}}
        _validate_report_shape(report)
        return report

    # integrity
    if not (isinstance(source_assertion, str) and _SOURCE_ID_PATTERN.match(source_assertion)):
        raise ProcessingError("source_assertion (source_id) is missing or invalid", code=6)
    if media_type != "video/mp4":
        raise ProcessingError("integrity input media_type must be 'video/mp4'", code=6)
    if not (_is_int(byte_size) and byte_size >= 0):
        raise ProcessingError("integrity input byte_size must be a non-negative integer", code=6)
    if not (isinstance(digest_value, str) and _SHA256_PATTERN.match(digest_value)):
        raise ProcessingError("integrity input digest value must be 64 lowercase hex chars", code=6)

    report = {
        **common,
        "input": {
            "artifact_id": artifact_id,
            "manifest_sha256": manifest_sha256,
            "source_assertion": source_assertion,
            "artifact_kind": "raw_media",
            "media_type": "video/mp4",
            "byte_size": byte_size,
            "digest": {"algorithm": "sha256", "value": digest_value},
        },
    }
    _validate_report_shape(report)
    return report


def serialize_report(report: dict[str, Any]) -> bytes:
    """Deterministic report bytes: UTF-8, sorted keys, 2-space indent, one \\n."""
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def derived_identity(report_bytes: bytes) -> str:
    """The derived metadata artifact identity is sha256(exact report bytes)."""
    return hashlib.sha256(report_bytes).hexdigest()


# ── internal helpers ─────────────────────────────────────────────────────────
def _canonical_bytes(mapping: dict[str, Any]) -> bytes:
    text = json.dumps(mapping, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


# frozen runtime shape guard (stdlib; JSON Schema validation stays in tests)
_COMMON_REQUIRED = ("schema_version", "report_kind", "processor", "parameters", "input")
_COMMON_ALLOWED = set(_COMMON_REQUIRED)
_IDENTITY_INPUT = {"artifact_id", "manifest_sha256"}
_INTEGRITY_INPUT = {
    "artifact_id", "manifest_sha256", "source_assertion", "artifact_kind",
    "media_type", "byte_size", "digest",
}


def _validate_report_shape(report: dict[str, Any]) -> None:
    """Assert the EXACT frozen report shape; unknown fields are forbidden."""
    if not isinstance(report, dict):
        raise ProcessingError("report must be a JSON object", code=6)
    unknown = set(report) - _COMMON_ALLOWED
    if unknown:
        raise ProcessingError(f"report has unknown fields: {sorted(unknown)}", code=6)
    for field in _COMMON_REQUIRED:
        if field not in report:
            raise ProcessingError(f"report missing required field: {field}", code=6)
    if not (_is_int(report["schema_version"]) and report["schema_version"] == 1):
        raise ProcessingError("report schema_version must be integer 1", code=6)
    if report["report_kind"] != REPORT_KIND:
        raise ProcessingError(f"report report_kind must be {REPORT_KIND!r}", code=6)
    processor = report["processor"]
    if not isinstance(processor, dict) or set(processor) != {"name", "version"}:
        raise ProcessingError("report processor must have exactly name and version", code=6)
    if processor["name"] != PROCESSOR_NAME or processor["version"] != PROCESSOR_VERSION:
        raise ProcessingError("report processor name/version are frozen", code=6)
    parameters = report["parameters"]
    if not isinstance(parameters, dict) or set(parameters) != {"profile"}:
        raise ProcessingError("report parameters must have exactly profile", code=6)
    profile = parameters["profile"]
    if profile not in PROFILES:
        raise ProcessingError(f"report parameters.profile must be one of {PROFILES}", code=6)
    inp = report["input"]
    if not isinstance(inp, dict):
        raise ProcessingError("report input must be an object", code=6)
    expected_keys = _IDENTITY_INPUT if profile == "identity" else _INTEGRITY_INPUT
    if set(inp) != expected_keys:
        raise ProcessingError(
            f"report input keys for profile {profile!r} must be exactly {sorted(expected_keys)}",
            code=6,
        )
