"""Polished deterministic local demonstration of the read-only processor pilot."""

from __future__ import annotations

from apps.processor_pilot import ProcessorInspection, run_processor_pilot
from packages.agent_contracts.canonical import canonical_json

COMMIT = "0000000000000000000000000000000000000000"


class DemoReadTool:
    def inspect(self) -> ProcessorInspection:
        return ProcessorInspection(
            database_schema_version=10,
            eligible_count=5,
            missing_count=2,
            prepared_count=1,
            complete_count=2,
        )


def main() -> int:
    result = run_processor_pilot(DemoReadTool(), canonical_commit=COMMIT)
    receipt = {
        "status": "pass",
        "proof_class": "standalone_read_only_processor_pilot",
        "model_provider_used": False,
        "worker_invoked": False,
        "mutation_performed": False,
        "classification": result.classification.primary_code,
        "operation": result.proposal.operation_code.value,
        "final_status": result.receipt.final_status.value,
        "observation_sha256": result.observation.digest_sha256,
        "proposal_sha256": result.proposal.digest_sha256,
        "receipt_sha256": result.receipt.digest_sha256,
        "explanation": result.explanation,
    }
    print(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
