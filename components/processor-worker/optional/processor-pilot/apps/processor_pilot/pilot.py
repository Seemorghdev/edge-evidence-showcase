"""Optional deterministic read-only processor pilot.

The pilot has one typed live capability: inspect the existing processor snapshot.
It never invokes the worker, opens a write transaction, mutates the spool, schedules
future work, or calls a model provider.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from apps.edge_agent import migration_history
from apps.processor_worker import provenance as processor_product_provenance
from apps.processor_worker import worker
from packages.agent_contracts.canonical import canonical_sha256
from packages.agent_contracts.model import (
    ApprovalRequirement,
    AuthorityReference,
    Classification,
    EvidenceReference,
    MutationClass,
    ProcessorIntegrityStatus,
    ProcessorObservation,
    Proposal,
    ReceiptStatus,
    Service,
    StructuredReceipt,
    build_structured_receipt,
)
from packages.agent_contracts.processor import (
    ProcessorClassificationCode,
    classify_processor,
    propose_processor,
)

_EXPECTED_CANONICAL_COMMIT = "0000000000000000000000000000000000000000"
_REQUIRED_DATABASE_SCHEMA_VERSION = 10
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SQLITE_TIMEOUT_SECONDS = 5.0


class ProcessorPilotError(RuntimeError):
    """Fail-closed pilot error carrying one stable finding code."""

    def __init__(self, finding: str) -> None:
        super().__init__(finding)
        self.finding = finding


@dataclass(frozen=True)
class ProcessorAgentContext:
    """Application-bound immutable context supplied to the framework-neutral core."""

    canonical_commit: str
    authority_instance: str = "local-processor-authority"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_commit",
            _bound_canonical_commit(self.canonical_commit),
        )
        object.__setattr__(
            self,
            "authority_instance",
            _bound_authority_instance(self.authority_instance),
        )


@dataclass(frozen=True)
class ProcessorInspection:
    """Typed result returned by the sole allowlisted read tool."""

    database_schema_version: int
    eligible_count: int
    missing_count: int
    prepared_count: int
    complete_count: int
    deferred_lock_count: int = 0
    identity_conflict_count: int = 0
    integrity_status: ProcessorIntegrityStatus = ProcessorIntegrityStatus.PASS

    def __post_init__(self) -> None:
        if (
            isinstance(self.database_schema_version, bool)
            or not isinstance(self.database_schema_version, int)
            or self.database_schema_version != _REQUIRED_DATABASE_SCHEMA_VERSION
        ):
            raise ValueError(
                "processor inspection requires observed database schema version 10"
            )
        values = (
            self.eligible_count,
            self.missing_count,
            self.prepared_count,
            self.complete_count,
            self.deferred_lock_count,
            self.identity_conflict_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise ValueError("inspection counts must be non-negative integers")
        if not isinstance(self.integrity_status, ProcessorIntegrityStatus):
            raise ValueError("integrity_status must be ProcessorIntegrityStatus")
        if self.integrity_status is ProcessorIntegrityStatus.UNAVAILABLE:
            raise ValueError(
                "unavailable authority cannot claim an observed database schema version"
            )
        if self.integrity_status is ProcessorIntegrityStatus.PASS:
            if (
                self.missing_count + self.prepared_count + self.complete_count
                != self.eligible_count
            ):
                raise ValueError(
                    "processor inspection state counts must equal eligible_count"
                )

    def semantic_payload(self) -> dict[str, int | str]:
        return {
            "complete_count": self.complete_count,
            "database_schema_version": self.database_schema_version,
            "deferred_lock_count": self.deferred_lock_count,
            "eligible_count": self.eligible_count,
            "identity_conflict_count": self.identity_conflict_count,
            "integrity_status": self.integrity_status.value,
            "missing_count": self.missing_count,
            "prepared_count": self.prepared_count,
        }


class ProcessorReadTool(Protocol):
    """The complete live tool surface allowed to the pilot."""

    def inspect(self) -> ProcessorInspection:
        """Return one immutable processor snapshot without mutation."""


def _read_exact_schema_version(database: Path) -> int:
    """Read canonical migration history without creating or mutating authority."""

    if not database.is_file():
        raise ProcessorPilotError("database_unavailable")
    try:
        connection = sqlite3.connect(
            database.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=_SQLITE_TIMEOUT_SECONDS,
        )
        try:
            history = migration_history.recorded_history(connection)
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        raise ProcessorPilotError("database_integrity_failure") from exc

    expected = migration_history.CANONICAL_HISTORY[:_REQUIRED_DATABASE_SCHEMA_VERSION]
    if history != expected:
        if history in {
            migration_history.CANONICAL_HISTORY[:version]
            for version in range(8, _REQUIRED_DATABASE_SCHEMA_VERSION)
        }:
            raise ProcessorPilotError("database_schema_unsupported")
        raise ProcessorPilotError("database_migration_required")
    return _REQUIRED_DATABASE_SCHEMA_VERSION


@dataclass(frozen=True)
class SQLiteProcessorReadTool:
    """Read the canonical SQLite authority through the worker's read-only snapshot."""

    database: Path

    def inspect(self) -> ProcessorInspection:
        database_schema_version = _read_exact_schema_version(self.database)
        try:
            candidates = worker.snapshot(self.database)
        except worker.ProcessorWorkerError as exc:
            if exc.finding in {
                "processing_job_identity_conflict",
                "processing_identity_conflict",
            }:
                return ProcessorInspection(
                    database_schema_version=database_schema_version,
                    eligible_count=0,
                    missing_count=0,
                    prepared_count=0,
                    complete_count=0,
                    identity_conflict_count=1,
                )
            if exc.finding in {
                "database_unavailable",
                "database_migration_required",
            }:
                raise ProcessorPilotError(exc.finding) from exc
            return ProcessorInspection(
                database_schema_version=database_schema_version,
                eligible_count=0,
                missing_count=0,
                prepared_count=0,
                complete_count=0,
                integrity_status=ProcessorIntegrityStatus.FAIL,
            )

        states = [candidate.prior_state for candidate in candidates]
        return ProcessorInspection(
            database_schema_version=database_schema_version,
            eligible_count=len(states),
            missing_count=states.count("MISSING"),
            prepared_count=states.count("PREPARED"),
            complete_count=states.count("COMPLETE"),
        )


_EXPLANATIONS = {
    ProcessorClassificationCode.INTEGRITY_FAILURE.value: (
        "The processor authority could not be proven internally consistent.",
    ),
    ProcessorClassificationCode.IDENTITY_CONFLICT.value: (
        "A processing row conflicts with the frozen deterministic processor identity.",
    ),
    ProcessorClassificationCode.UNAVAILABLE.value: (
        "The processor authority is unavailable for a read-only observation.",
    ),
    ProcessorClassificationCode.PREPARED_BACKLOG.value: (
        "Eligible processor work has a deterministic PREPARED job that remains resumable.",
    ),
    ProcessorClassificationCode.MISSING_BACKLOG.value: (
        "Eligible processor work is missing its deterministic processing job.",
    ),
    ProcessorClassificationCode.DEFERRED_BUSY.value: (
        "Processor work is deferred because the shared spool lock is busy.",
    ),
    ProcessorClassificationCode.CONVERGED.value: (
        "All eligible processor work is already complete.",
    ),
}


@dataclass(frozen=True)
class ProcessorPilotResult:
    """Complete inspect → classify → explain → propose read-only result."""

    schema: str
    observation: ProcessorObservation
    classification: Classification
    explanation: tuple[str, ...]
    proposal: Proposal
    receipt: StructuredReceipt

    @property
    def proposal_requirement(self) -> ApprovalRequirement:
        """Return the exact frozen policy requirement already present in the proposal."""

        return self.proposal.approval_requirement

    def public(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "observation": self.observation,
            "classification": self.classification,
            "explanation": self.explanation,
            "proposal": self.proposal,
            "receipt": self.receipt,
        }


def _finding_codes(inspection: ProcessorInspection) -> tuple[str, ...]:
    values: set[str] = set()
    if inspection.integrity_status is ProcessorIntegrityStatus.FAIL:
        values.add(ProcessorClassificationCode.INTEGRITY_FAILURE.value)
    if inspection.integrity_status is ProcessorIntegrityStatus.UNAVAILABLE:
        values.add(ProcessorClassificationCode.UNAVAILABLE.value)
    if inspection.identity_conflict_count:
        values.add(ProcessorClassificationCode.IDENTITY_CONFLICT.value)
    if inspection.prepared_count:
        values.add(ProcessorClassificationCode.PREPARED_BACKLOG.value)
    if inspection.missing_count:
        values.add(ProcessorClassificationCode.MISSING_BACKLOG.value)
    if inspection.deferred_lock_count:
        values.add(ProcessorClassificationCode.DEFERRED_BUSY.value)
    if not values:
        values.add(ProcessorClassificationCode.CONVERGED.value)
    return tuple(sorted(values))


def _bound_canonical_commit(canonical_commit: str) -> str:
    if not isinstance(canonical_commit, str) or _GIT_SHA.fullmatch(canonical_commit) is None:
        raise ProcessorPilotError("canonical_commit_invalid")
    if _GIT_SHA.fullmatch(_EXPECTED_CANONICAL_COMMIT) is None:
        raise ProcessorPilotError("product_provenance_unresolved")

    base_commit = processor_product_provenance.CANONICAL_COMMIT
    if not isinstance(base_commit, str) or _GIT_SHA.fullmatch(base_commit) is None:
        raise ProcessorPilotError("base_product_provenance_unresolved")
    if base_commit != _EXPECTED_CANONICAL_COMMIT:
        raise ProcessorPilotError("base_product_provenance_mismatch")
    if canonical_commit != _EXPECTED_CANONICAL_COMMIT:
        raise ProcessorPilotError("canonical_commit_mismatch")
    return _EXPECTED_CANONICAL_COMMIT


def _bound_authority_instance(authority_instance: str) -> str:
    if (
        not isinstance(authority_instance, str)
        or _SAFE_IDENTIFIER.fullmatch(authority_instance) is None
    ):
        raise ProcessorPilotError("authority_instance_invalid")
    lowered = authority_instance.lower()
    if any(
        term in lowered
        for term in (
            "secret",
            "token",
            "password",
            "private_key",
            "/home/",
            "/users/",
        )
    ):
        raise ProcessorPilotError("authority_instance_invalid")
    return authority_instance


def _observation(
    inspection: ProcessorInspection,
    *,
    context: ProcessorAgentContext,
) -> ProcessorObservation:
    semantic_payload = inspection.semantic_payload()
    semantic_sha256 = canonical_sha256(semantic_payload)
    authority = AuthorityReference(
        service=Service.PROCESSOR,
        canonical_repository="private-redacted",
        canonical_commit=context.canonical_commit,
        authority_instance=context.authority_instance,
        projection_schema="processor-readonly-pilot.v1",
        contract_version="bounded-agent-contracts.v2",
        database_schema_version=inspection.database_schema_version,
        observed_snapshot_sha256=semantic_sha256,
        proof_class="local-read-only-processor-pilot",
    )
    findings = _finding_codes(inspection)
    evidence = tuple(
        EvidenceReference(
            finding_code=finding,
            evidence_code="processor-readonly-snapshot.v1",
            authority_reference_sha256=authority.digest_sha256,
            evidence_sha256=canonical_sha256(
                {"finding_code": finding, "snapshot": semantic_payload}
            ),
        )
        for finding in findings
    )
    return ProcessorObservation(
        authority=authority,
        semantic_input_sha256=semantic_sha256,
        finding_codes=findings,
        evidence_references=evidence,
        eligible_count=inspection.eligible_count,
        missing_count=inspection.missing_count,
        prepared_count=inspection.prepared_count,
        complete_count=inspection.complete_count,
        deferred_lock_count=inspection.deferred_lock_count,
        identity_conflict_count=inspection.identity_conflict_count,
        integrity_status=inspection.integrity_status,
    )


class ProcessorAgentCore:
    """One-shot framework-neutral processor inspection, proposal, and receipt core."""

    def __init__(
        self,
        read_tool: ProcessorReadTool,
        *,
        context: ProcessorAgentContext,
    ) -> None:
        if not isinstance(context, ProcessorAgentContext):
            raise TypeError("processor agent core requires ProcessorAgentContext")
        self._read_tool = read_tool
        self.context = context
        self._completed = False

    def inspect(self) -> ProcessorPilotResult:
        """Inspect exactly once, return a proposal-only read result, and stop."""

        if self._completed:
            raise ProcessorPilotError("processor_core_already_completed")
        self._completed = True

        inspection = self._read_tool.inspect()
        if not isinstance(inspection, ProcessorInspection):
            raise TypeError("processor read tool must return ProcessorInspection")
        observation = _observation(inspection, context=self.context)
        classification = classify_processor(observation)
        explanation = _EXPLANATIONS[classification.primary_code]
        proposal = propose_processor(observation, classification)
        if proposal.mutation_class is MutationClass.BOUNDED_EXECUTION:
            raise RuntimeError("read-only core produced an executable proposal")

        receipt = build_structured_receipt(
            authority=observation.authority,
            observation=observation,
            classification=classification,
            proposal=proposal,
        )
        if receipt.final_status is not ReceiptStatus.READ_ONLY_COMPLETE:
            raise RuntimeError("read-only pilot produced a non-read-only receipt")
        if any(
            value is not None
            for value in (
                receipt.approval_sha256,
                receipt.execution_sha256,
                receipt.verification_sha256,
            )
        ):
            raise RuntimeError("read-only pilot receipt contains execution bindings")

        return ProcessorPilotResult(
            schema="processor-readonly-pilot-result.v1",
            observation=observation,
            classification=classification,
            explanation=explanation,
            proposal=proposal,
            receipt=receipt,
        )


def run_processor_pilot(
    read_tool: ProcessorReadTool,
    *,
    canonical_commit: str,
    authority_instance: str = "local-processor-authority",
) -> ProcessorPilotResult:
    """Compatibility facade over one application-bound read-only core run."""

    context = ProcessorAgentContext(
        canonical_commit=canonical_commit,
        authority_instance=authority_instance,
    )
    return ProcessorAgentCore(read_tool, context=context).inspect()
