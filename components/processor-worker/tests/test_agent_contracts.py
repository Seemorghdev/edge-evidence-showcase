from __future__ import annotations

from dataclasses import replace

import pytest

from packages.agent_contracts import (
    ApprovalRequirement,
    AuthorityReference,
    ContractViolation,
    EvidenceReference,
    MutationClass,
    PolicyDisposition,
    PolicyPhase,
    ProcessorIntegrityStatus,
    ProcessorObservation,
    ProcessorOperation,
    ReceiptStatus,
    Service,
    build_structured_receipt,
    canonical_sha256,
    classify_processor,
    propose_processor,
    resolve_processor_policy,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
GIT_SHA = "c" * 40


def _observation() -> ProcessorObservation:
    authority = AuthorityReference(
        service=Service.PROCESSOR,
        canonical_repository="private-redacted",
        canonical_commit=GIT_SHA,
        authority_instance="public-contract-fixture",
        projection_schema="operational-truth.v1",
        contract_version="bounded-agent-contracts.v2",
        database_schema_version=10,
        observed_snapshot_sha256=SHA_A,
        proof_class="model-free-public-contract",
    )
    finding = "PROCESSOR_MISSING_BACKLOG"
    evidence = EvidenceReference(
        finding_code=finding,
        evidence_code="processor-backlog-counts-v1",
        authority_reference_sha256=authority.digest_sha256,
        evidence_sha256=SHA_B,
    )
    return ProcessorObservation(
        authority=authority,
        semantic_input_sha256=SHA_A,
        finding_codes=(finding,),
        evidence_references=(evidence,),
        eligible_count=1,
        missing_count=1,
        prepared_count=0,
        complete_count=0,
        deferred_lock_count=0,
        identity_conflict_count=0,
        integrity_status=ProcessorIntegrityStatus.PASS,
    )


def test_processor_contract_is_model_free_deterministic_and_read_only() -> None:
    observation = _observation()
    classification = classify_processor(observation)
    proposal = propose_processor(observation, classification)
    receipt = build_structured_receipt(
        authority=observation.authority,
        observation=observation,
        classification=classification,
        proposal=proposal,
    )

    assert classification.primary_code == "PROCESSOR_MISSING_BACKLOG"
    assert proposal.operation_code is ProcessorOperation.PROPOSE_CATCH_UP
    assert proposal.policy_phase is PolicyPhase.WAVE_C
    assert proposal.disposition is PolicyDisposition.ALLOW
    assert proposal.mutation_class is MutationClass.PROPOSAL_ONLY
    assert proposal.approval_requirement is ApprovalRequirement.NONE
    assert receipt.final_status is ReceiptStatus.READ_ONLY_COMPLETE
    assert receipt.approval_sha256 is None
    assert receipt.execution_sha256 is None
    assert receipt.verification_sha256 is None
    assert canonical_sha256(receipt) == receipt.digest_sha256


def test_processor_wave_c_keeps_worker_execution_forbidden() -> None:
    row = resolve_processor_policy(ProcessorOperation.INVOKE_WORKER_RUN)
    assert row.wave_c is PolicyDisposition.FORBID
    assert row.future_successor is PolicyDisposition.ALLOW
    assert row.approval_requirement is ApprovalRequirement.EXPLICIT_OWNER


def test_processor_contract_rejects_forged_classification() -> None:
    observation = _observation()
    classification = classify_processor(observation)
    forged = replace(classification, primary_code="PROCESSOR_CONVERGED")
    proposal = propose_processor(observation, classification)

    with pytest.raises(ContractViolation):
        build_structured_receipt(
            authority=observation.authority,
            observation=observation,
            classification=forged,
            proposal=proposal,
        )
