"""Deterministic processor observation classification and proposal design."""

from __future__ import annotations

import re
from enum import Enum

from .model import (
    Actionability,
    ApprovalDecision,
    ApprovalOutcome,
    Classification,
    ContractViolation,
    MutationClass,
    PolicyDisposition,
    PolicyPhase,
    ProcessorIntegrityStatus,
    ProcessorObservation,
    ProcessorOperation,
    Proposal,
    Service,
    Severity,
    approval_binds_proposal,
)
from .policy import resolve_processor_policy

_PROCESSOR_POLICY_VERSION = "processor-mutation-policy.v2"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProcessorClassificationCode(str, Enum):
    INTEGRITY_FAILURE = "PROCESSOR_INTEGRITY_FAILURE"
    IDENTITY_CONFLICT = "PROCESSOR_IDENTITY_CONFLICT"
    UNAVAILABLE = "PROCESSOR_UNAVAILABLE"
    PREPARED_BACKLOG = "PROCESSOR_PREPARED_BACKLOG"
    MISSING_BACKLOG = "PROCESSOR_MISSING_BACKLOG"
    DEFERRED_BUSY = "PROCESSOR_DEFERRED_BUSY"
    CONVERGED = "PROCESSOR_CONVERGED"


def _findings(observation: ProcessorObservation) -> tuple[str, ...]:
    values: set[str] = set()
    if observation.integrity_status is ProcessorIntegrityStatus.FAIL:
        values.add(ProcessorClassificationCode.INTEGRITY_FAILURE.value)
    if observation.integrity_status is ProcessorIntegrityStatus.UNAVAILABLE:
        values.add(ProcessorClassificationCode.UNAVAILABLE.value)
    if observation.identity_conflict_count:
        values.add(ProcessorClassificationCode.IDENTITY_CONFLICT.value)
    if observation.prepared_count:
        values.add(ProcessorClassificationCode.PREPARED_BACKLOG.value)
    if observation.missing_count:
        values.add(ProcessorClassificationCode.MISSING_BACKLOG.value)
    if observation.deferred_lock_count:
        values.add(ProcessorClassificationCode.DEFERRED_BUSY.value)
    if not values:
        values.add(ProcessorClassificationCode.CONVERGED.value)
    return tuple(sorted(values))


def classify_processor(observation: ProcessorObservation) -> Classification:
    if not isinstance(observation, ProcessorObservation):
        raise ContractViolation(
            "processor classifier requires ProcessorObservation"
        )
    findings = _findings(observation)
    if observation.finding_codes != findings:
        raise ContractViolation(
            "processor observation findings contradict state"
        )
    if observation.integrity_status is ProcessorIntegrityStatus.FAIL:
        code = ProcessorClassificationCode.INTEGRITY_FAILURE
        severity = Severity.FAIL
        action = Actionability.ESCALATE
    elif observation.identity_conflict_count:
        code = ProcessorClassificationCode.IDENTITY_CONFLICT
        severity = Severity.FAIL
        action = Actionability.ESCALATE
    elif observation.integrity_status is ProcessorIntegrityStatus.UNAVAILABLE:
        code = ProcessorClassificationCode.UNAVAILABLE
        severity = Severity.UNAVAILABLE
        action = Actionability.RETRY
    elif observation.prepared_count:
        code = ProcessorClassificationCode.PREPARED_BACKLOG
        severity = Severity.ATTENTION
        action = Actionability.PROPOSE
    elif observation.missing_count:
        code = ProcessorClassificationCode.MISSING_BACKLOG
        severity = Severity.ATTENTION
        action = Actionability.PROPOSE
    elif observation.deferred_lock_count:
        code = ProcessorClassificationCode.DEFERRED_BUSY
        severity = Severity.ATTENTION
        action = Actionability.RETRY
    else:
        code = ProcessorClassificationCode.CONVERGED
        severity = Severity.PASS
        action = Actionability.NONE
    return Classification(
        service=Service.PROCESSOR,
        primary_code=code.value,
        severity=severity,
        actionability=action,
        finding_codes=findings,
        observation_sha256=observation.digest_sha256,
        classifier_version="processor-classifier.v1",
    )


def validate_processor_classification(
    observation: ProcessorObservation,
    classification: Classification,
) -> None:
    if not isinstance(observation, ProcessorObservation):
        raise ContractViolation(
            "processor classification validation requires ProcessorObservation"
        )
    if not isinstance(classification, Classification):
        raise ContractViolation("classification must be Classification")
    expected = classify_processor(observation)
    if classification != expected:
        raise ContractViolation(
            "processor classification contradicts observation"
        )


def _allowed_operations(
    classification: Classification,
) -> frozenset[ProcessorOperation]:
    code = classification.primary_code
    if code == ProcessorClassificationCode.CONVERGED.value:
        return frozenset({ProcessorOperation.NO_ACTION})
    if code in {
        ProcessorClassificationCode.DEFERRED_BUSY.value,
        ProcessorClassificationCode.UNAVAILABLE.value,
    }:
        return frozenset({ProcessorOperation.RETRY_OBSERVATION})
    if code in {
        ProcessorClassificationCode.MISSING_BACKLOG.value,
        ProcessorClassificationCode.PREPARED_BACKLOG.value,
    }:
        return frozenset(
            {
                ProcessorOperation.PROPOSE_CATCH_UP,
                ProcessorOperation.INVOKE_WORKER_RUN,
            }
        )
    return frozenset({ProcessorOperation.ESCALATE_STATE})


def _parameters(
    observation: ProcessorObservation,
    operation: ProcessorOperation,
) -> tuple[tuple[str, object], ...]:
    if operation is ProcessorOperation.NO_ACTION:
        return ()
    if operation in {
        ProcessorOperation.RETRY_OBSERVATION,
        ProcessorOperation.ESCALATE_STATE,
    }:
        return (
            (
                "expected_snapshot_sha256",
                observation.semantic_input_sha256,
            ),
        )
    if operation in {
        ProcessorOperation.PROPOSE_CATCH_UP,
        ProcessorOperation.INVOKE_WORKER_RUN,
    }:
        return tuple(
            sorted(
                (
                    ("eligible_count", observation.eligible_count),
                    (
                        "expected_snapshot_sha256",
                        observation.semantic_input_sha256,
                    ),
                )
            )
        )
    raise ContractViolation(
        "processor operation is not proposal-compatible"
    )


def _make_proposal(
    observation: ProcessorObservation,
    classification: Classification,
    operation: ProcessorOperation,
    phase: PolicyPhase,
) -> Proposal:
    validate_processor_classification(observation, classification)
    if operation not in _allowed_operations(classification):
        raise ContractViolation(
            "processor operation contradicts classification"
        )
    row = resolve_processor_policy(operation)
    disposition = row.disposition_for(phase)
    if (
        disposition is PolicyDisposition.FORBID
        or row.mutation_class is MutationClass.FORBIDDEN
    ):
        raise ContractViolation(
            "processor operation is forbidden in selected policy phase"
        )
    return Proposal(
        service=Service.PROCESSOR,
        authority_reference_sha256=observation.authority.digest_sha256,
        operation_code=operation,
        policy_phase=phase,
        disposition=disposition,
        mutation_class=row.mutation_class,
        exact_parameters=_parameters(observation, operation),
        observation_sha256=observation.digest_sha256,
        classification_sha256=classification.digest_sha256,
        approval_requirement=row.approval_requirement,
        precondition_codes=row.precondition_codes,
        required_evidence_codes=row.required_evidence_codes,
        verification_requirement_codes=row.verification_requirement_codes,
        policy_version=_PROCESSOR_POLICY_VERSION,
    )


def propose_processor(
    observation: ProcessorObservation,
    classification: Classification | None = None,
) -> Proposal:
    classification = classification or classify_processor(observation)
    validate_processor_classification(observation, classification)
    code = classification.primary_code
    if code == ProcessorClassificationCode.CONVERGED.value:
        operation = ProcessorOperation.NO_ACTION
    elif code in {
        ProcessorClassificationCode.DEFERRED_BUSY.value,
        ProcessorClassificationCode.UNAVAILABLE.value,
    }:
        operation = ProcessorOperation.RETRY_OBSERVATION
    elif code in {
        ProcessorClassificationCode.MISSING_BACKLOG.value,
        ProcessorClassificationCode.PREPARED_BACKLOG.value,
    }:
        operation = ProcessorOperation.PROPOSE_CATCH_UP
    else:
        operation = ProcessorOperation.ESCALATE_STATE
    return _make_proposal(
        observation,
        classification,
        operation,
        PolicyPhase.WAVE_C,
    )


def _validate_proposal_fields(
    observation: ProcessorObservation,
    classification: Classification,
    proposal: Proposal,
    *,
    expected_parameters: tuple[tuple[str, object], ...],
) -> None:
    validate_processor_classification(observation, classification)
    if not isinstance(proposal, Proposal):
        raise ContractViolation("proposal must be Proposal")
    if proposal.service is not Service.PROCESSOR:
        raise ContractViolation("processor proposal has wrong service")
    if not isinstance(proposal.operation_code, ProcessorOperation):
        raise ContractViolation(
            "processor proposal has wrong operation type"
        )
    if proposal.operation_code not in _allowed_operations(classification):
        raise ContractViolation(
            "processor proposal contradicts classification"
        )
    row = resolve_processor_policy(proposal.operation_code)
    expected_disposition = row.disposition_for(proposal.policy_phase)
    if expected_disposition is PolicyDisposition.FORBID:
        raise ContractViolation(
            "processor proposal operation is forbidden in selected phase"
        )
    expected = {
        "authority_reference_sha256": observation.authority.digest_sha256,
        "disposition": expected_disposition,
        "mutation_class": row.mutation_class,
        "exact_parameters": expected_parameters,
        "observation_sha256": observation.digest_sha256,
        "classification_sha256": classification.digest_sha256,
        "approval_requirement": row.approval_requirement,
        "precondition_codes": row.precondition_codes,
        "required_evidence_codes": row.required_evidence_codes,
        "verification_requirement_codes": row.verification_requirement_codes,
        "policy_version": _PROCESSOR_POLICY_VERSION,
    }
    for field, value in expected.items():
        if getattr(proposal, field) != value:
            raise ContractViolation(
                f"processor proposal {field} differs from frozen policy"
            )


def validate_processor_proposal(
    observation: ProcessorObservation,
    classification: Classification,
    proposal: Proposal,
) -> None:
    successor_fields = {
        "authority_context_sha256",
        "candidate_count",
        "candidate_manifest_sha256",
        "implementation_identity_sha256",
    }
    if isinstance(proposal, Proposal):
        supplied_fields = {
            name for name, _value in proposal.exact_parameters
        }
        if supplied_fields.intersection(successor_fields):
            raise ContractViolation(
                "successor proposal requires fully bound validation"
            )
    _validate_proposal_fields(
        observation,
        classification,
        proposal,
        expected_parameters=_parameters(
            observation,
            proposal.operation_code,
        ),
    )


def _successor_sha(value: str, field: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ContractViolation(
            f"{field} must be a lowercase SHA-256"
        )


def _successor_parameters(
    *,
    authority_context_sha256: str,
    candidate_count: int,
    candidate_manifest_sha256: str,
    implementation_identity_sha256: str,
) -> tuple[tuple[str, object], ...]:
    _successor_sha(
        authority_context_sha256,
        "authority_context_sha256",
    )
    _successor_sha(
        candidate_manifest_sha256,
        "candidate_manifest_sha256",
    )
    _successor_sha(
        implementation_identity_sha256,
        "implementation_identity_sha256",
    )
    if (
        isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count < 1
    ):
        raise ContractViolation(
            "candidate_count must be a positive integer"
        )
    return (
        ("authority_context_sha256", authority_context_sha256),
        ("candidate_count", candidate_count),
        ("candidate_manifest_sha256", candidate_manifest_sha256),
        (
            "implementation_identity_sha256",
            implementation_identity_sha256,
        ),
    )


def propose_processor_successor(
    observation: ProcessorObservation,
    classification: Classification,
    *,
    authority_context_sha256: str,
    candidate_manifest_sha256: str,
    implementation_identity_sha256: str,
    candidate_count: int,
) -> Proposal:
    """Build the exact item-level future-successor proposal frozen for PMS-B01."""
    validate_processor_classification(observation, classification)
    if (
        ProcessorOperation.INVOKE_WORKER_RUN
        not in _allowed_operations(classification)
    ):
        raise ContractViolation(
            "processor classification does not permit exact worker invocation"
        )
    if (
        observation.semantic_input_sha256
        != candidate_manifest_sha256
    ):
        raise ContractViolation(
            "observation does not bind the exact candidate manifest"
        )
    row = resolve_processor_policy(
        ProcessorOperation.INVOKE_WORKER_RUN
    )
    parameters = _successor_parameters(
        authority_context_sha256=authority_context_sha256,
        candidate_count=candidate_count,
        candidate_manifest_sha256=candidate_manifest_sha256,
        implementation_identity_sha256=(
            implementation_identity_sha256
        ),
    )
    proposal = Proposal(
        service=Service.PROCESSOR,
        authority_reference_sha256=observation.authority.digest_sha256,
        operation_code=ProcessorOperation.INVOKE_WORKER_RUN,
        policy_phase=PolicyPhase.FUTURE_SUCCESSOR,
        disposition=row.future_successor,
        mutation_class=row.mutation_class,
        exact_parameters=parameters,
        observation_sha256=observation.digest_sha256,
        classification_sha256=classification.digest_sha256,
        approval_requirement=row.approval_requirement,
        precondition_codes=row.precondition_codes,
        required_evidence_codes=row.required_evidence_codes,
        verification_requirement_codes=(
            row.verification_requirement_codes
        ),
        policy_version=_PROCESSOR_POLICY_VERSION,
    )
    validate_processor_successor_proposal(
        observation,
        classification,
        proposal,
        authority_context_sha256=authority_context_sha256,
        candidate_count=candidate_count,
        candidate_manifest_sha256=candidate_manifest_sha256,
        implementation_identity_sha256=(
            implementation_identity_sha256
        ),
    )
    return proposal


def validate_processor_successor_proposal(
    observation: ProcessorObservation,
    classification: Classification,
    proposal: Proposal,
    *,
    authority_context_sha256: str,
    candidate_count: int,
    candidate_manifest_sha256: str,
    implementation_identity_sha256: str,
) -> None:
    expected = _successor_parameters(
        authority_context_sha256=authority_context_sha256,
        candidate_count=candidate_count,
        candidate_manifest_sha256=candidate_manifest_sha256,
        implementation_identity_sha256=(
            implementation_identity_sha256
        ),
    )
    _validate_proposal_fields(
        observation,
        classification,
        proposal,
        expected_parameters=expected,
    )
    if (
        proposal.operation_code
        is not ProcessorOperation.INVOKE_WORKER_RUN
    ):
        raise ContractViolation(
            "successor proposal must invoke the processor worker"
        )
    if proposal.policy_phase is not PolicyPhase.FUTURE_SUCCESSOR:
        raise ContractViolation(
            "successor proposal must use future-successor policy"
        )
    if proposal.exact_parameters != expected:
        raise ContractViolation(
            "successor proposal parameters differ from exact manifest binding"
        )
    if (
        proposal.authority_reference_sha256
        != observation.authority.digest_sha256
    ):
        raise ContractViolation(
            "successor proposal authority differs"
        )
    if proposal.observation_sha256 != observation.digest_sha256:
        raise ContractViolation(
            "successor proposal observation differs"
        )
    if (
        observation.semantic_input_sha256
        != candidate_manifest_sha256
    ):
        raise ContractViolation(
            "observation semantic input differs from candidate manifest"
        )


def build_processor_owner_approval(
    proposal: Proposal,
    *,
    approver_reference: str,
    outcome: ApprovalOutcome = ApprovalOutcome.APPROVE,
) -> ApprovalDecision:
    if (
        proposal.operation_code
        is not ProcessorOperation.INVOKE_WORKER_RUN
    ):
        raise ContractViolation(
            "owner approval is only valid for exact processor invocation"
        )
    return ApprovalDecision(
        service=Service.PROCESSOR,
        outcome=outcome,
        proposal_sha256=proposal.digest_sha256,
        authority_reference_sha256=(
            proposal.authority_reference_sha256
        ),
        observation_sha256=proposal.observation_sha256,
        classification_sha256=proposal.classification_sha256,
        operation_code=proposal.operation_code,
        parameter_sha256=proposal.parameter_sha256,
        approval_scope_sha256=(
            proposal.approval_scope.digest_sha256
        ),
        approver_reference=approver_reference,
        policy_version=proposal.policy_version,
    )


def validate_processor_owner_approval(
    proposal: Proposal,
    approval: ApprovalDecision,
    current_observation_sha256: str,
) -> None:
    if not isinstance(approval, ApprovalDecision):
        raise ContractViolation(
            "approval must be ApprovalDecision"
        )
    if approval.outcome is not ApprovalOutcome.APPROVE:
        raise ContractViolation(
            "exact processor invocation requires approve outcome"
        )
    if not approval_binds_proposal(
        approval,
        proposal,
        current_observation_sha256,
    ):
        raise ContractViolation(
            "owner approval does not bind exact proposal and scope"
        )
