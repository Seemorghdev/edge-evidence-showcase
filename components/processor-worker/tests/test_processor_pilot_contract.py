"""Standalone model-free tests for the optional read-only processor pilot."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from apps.processor_pilot import (
    ProcessorInspection,
    ProcessorPilotError,
    run_processor_pilot,
)
from apps.processor_worker import provenance as processor_product_provenance
from packages.agent_contracts.canonical import canonical_json
from packages.agent_contracts.model import ProcessorOperation, ReceiptStatus

COMMIT = "0000000000000000000000000000000000000000"
ROOT = Path(__file__).resolve().parents[1]


class FixedReadTool:
    def __init__(self, inspection: ProcessorInspection) -> None:
        self.inspection = inspection
        self.calls = 0

    def inspect(self) -> ProcessorInspection:
        self.calls += 1
        return self.inspection


def _inspection(**overrides: object) -> ProcessorInspection:
    values: dict[str, object] = {
        "database_schema_version": 10,
        "eligible_count": 3,
        "missing_count": 2,
        "prepared_count": 0,
        "complete_count": 1,
    }
    values.update(overrides)
    return ProcessorInspection(**values)  # type: ignore[arg-type]


def test_optional_pilot_is_deterministic_model_free_and_read_only() -> None:
    inspection = _inspection()
    first_tool = FixedReadTool(inspection)
    second_tool = FixedReadTool(inspection)
    first = run_processor_pilot(first_tool, canonical_commit=COMMIT)
    second = run_processor_pilot(second_tool, canonical_commit=COMMIT)

    assert first_tool.calls == second_tool.calls == 1
    assert canonical_json(first.public()) == canonical_json(second.public())
    assert processor_product_provenance.CANONICAL_COMMIT == COMMIT
    assert first.observation.authority.canonical_commit == COMMIT
    assert first.observation.authority.database_schema_version == 10
    assert first.classification.primary_code == "PROCESSOR_MISSING_BACKLOG"
    assert first.proposal.operation_code is ProcessorOperation.PROPOSE_CATCH_UP
    assert first.receipt.final_status is ReceiptStatus.READ_ONLY_COMPLETE
    assert first.receipt.approval_sha256 is None
    assert first.receipt.execution_sha256 is None
    assert first.receipt.verification_sha256 is None


def test_well_formed_incorrect_canonical_commit_is_rejected_before_read() -> None:
    wrong = "0" * 40 if COMMIT != "0" * 40 else "1" * 40
    tool = FixedReadTool(_inspection())
    with pytest.raises(ProcessorPilotError, match="canonical_commit_mismatch"):
        run_processor_pilot(tool, canonical_commit=wrong)
    assert tool.calls == 0


def test_mismatched_base_product_provenance_is_rejected_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrong = "0" * 40 if COMMIT != "0" * 40 else "1" * 40
    monkeypatch.setattr(
        processor_product_provenance,
        "CANONICAL_COMMIT",
        wrong,
    )
    tool = FixedReadTool(_inspection())
    with pytest.raises(
        ProcessorPilotError,
        match="base_product_provenance_mismatch",
    ):
        run_processor_pilot(tool, canonical_commit=COMMIT)
    assert tool.calls == 0


def test_optional_pilot_converged_path_is_no_action() -> None:
    result = run_processor_pilot(
        FixedReadTool(
            _inspection(
                eligible_count=2,
                missing_count=0,
                prepared_count=0,
                complete_count=2,
            )
        ),
        canonical_commit=COMMIT,
    )
    assert result.classification.primary_code == "PROCESSOR_CONVERGED"
    assert result.proposal.operation_code is ProcessorOperation.NO_ACTION
    assert result.receipt.final_status is ReceiptStatus.READ_ONLY_COMPLETE


def test_pilot_is_a_separate_installable_distribution() -> None:
    base = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional = tomllib.loads(
        (ROOT / "optional" / "processor-pilot" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert "processor-pilot" not in base["project"].get("scripts", {})
    assert "processor-pilot" not in base["project"].get(
        "optional-dependencies", {}
    )
    assert base["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "apps",
        "apps.edge_agent*",
        "apps.processor_worker*",
        "packages*",
    ]
    assert optional["project"]["scripts"]["processor-pilot"] == (
        "apps.processor_pilot.cli:main"
    )
    assert optional["tool"]["setuptools"]["packages"] == [
        "apps.processor_pilot"
    ]
