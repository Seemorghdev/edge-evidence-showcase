"""Deterministic artifact-fingerprint processing package.

Pure identity and report layer (no I/O, standard-library only), mirroring the
finalize.py / register.py pure-core split. The effectful orchestration (spool
lock, evidence gate, filesystem publication, SQLite transaction) lives in
apps/edge_agent/process.py.
"""

from __future__ import annotations

from packages.processing.fingerprint import (
    ARTIFACT_KIND,
    MEDIA_TYPE,
    OUTPUT_CONTRACT,
    PROCESSOR_NAME,
    PROCESSOR_VERSION,
    RELATION_TYPE,
    ProcessingError,
    build_report,
    canonical_parameters,
    derived_identity,
    job_id_for,
    parameters_sha256,
    serialize_report,
)

__all__ = [
    "ARTIFACT_KIND",
    "MEDIA_TYPE",
    "OUTPUT_CONTRACT",
    "PROCESSOR_NAME",
    "PROCESSOR_VERSION",
    "RELATION_TYPE",
    "ProcessingError",
    "build_report",
    "canonical_parameters",
    "derived_identity",
    "job_id_for",
    "parameters_sha256",
    "serialize_report",
]