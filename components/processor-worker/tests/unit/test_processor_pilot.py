"""Acceptance tests for the optional read-only processor pilot."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from apps.processor_pilot import (
    ProcessorAgentContext,
    ProcessorAgentCore,
    ProcessorInspection,
    ProcessorPilotError,
    SQLiteProcessorReadTool,
    run_processor_pilot,
)
from apps.processor_pilot import pilot as pilot_module
from apps.processor_worker import provenance as processor_product_provenance
from packages.agent_contracts.canonical import canonical_json
from packages.agent_contracts.model import (
    ApprovalRequirement,
    MutationClass,
    ProcessorIntegrityStatus,
    ProcessorOperation,
    ReceiptStatus,
)
from packages.database import migrations

TEST_COMMIT = "a" * 40
WRONG_COMMIT = "b" * 40


@pytest.fixture(autouse=True)
def _bind_test_product_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pilot_module, "_EXPECTED_CANONICAL_COMMIT", TEST_COMMIT)
    monkeypatch.setattr(
        processor_product_provenance,
        "CANONICAL_COMMIT",
        TEST_COMMIT,
    )


class FixedReadTool:
    def __init__(self, inspection: object) -> None:
        self.inspection = inspection
        self.calls = 0

    def inspect(self) -> object:
        self.calls += 1
        return self.inspection


def _inspection(**overrides: object) -> ProcessorInspection:
    values: dict[str, object] = {
        "database_schema_version": 10,
        "eligible_count": 4,
        "missing_count": 2,
        "prepared_count": 1,
        "complete_count": 1,
    }
    values.update(overrides)
    return ProcessorInspection(**values)  # type: ignore[arg-type]


def _directory_inventory(root: Path) -> dict[str, tuple[str, int, int, int]]:
    inventory: dict[str, tuple[str, int, int, int]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            inventory[relative] = (digest, stat.st_size, stat.st_mode, stat.st_mtime_ns)
        elif path.is_dir():
            inventory[relative + "/"] = ("directory", 0, stat.st_mode, stat.st_mtime_ns)
    return inventory


def _migrate_to(
    database: Path,
    version: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, "MIGRATIONS", canonical[:version])
    migrations.migrate(database)
    monkeypatch.setattr(migrations, "MIGRATIONS", canonical)


def test_pilot_is_deterministic_and_stops_at_read_only_complete() -> None:
    tool = FixedReadTool(_inspection())
    first = run_processor_pilot(tool, canonical_commit=TEST_COMMIT)
    second_tool = FixedReadTool(tool.inspection)
    second = run_processor_pilot(second_tool, canonical_commit=TEST_COMMIT)

    assert tool.calls == 1
    assert second_tool.calls == 1
    assert canonical_json(first.public()) == canonical_json(second.public())
    assert first.observation.authority.database_schema_version == 10
    assert first.classification.primary_code == "PROCESSOR_PREPARED_BACKLOG"
    assert first.proposal.operation_code is ProcessorOperation.PROPOSE_CATCH_UP
    assert first.proposal.mutation_class is MutationClass.PROPOSAL_ONLY
    assert first.proposal_requirement is ApprovalRequirement.NONE
    assert first.receipt.final_status is ReceiptStatus.READ_ONLY_COMPLETE
    assert first.receipt.approval_sha256 is None
    assert first.receipt.execution_sha256 is None
    assert first.receipt.verification_sha256 is None


def test_direct_core_matches_facade_and_cannot_inspect_twice() -> None:
    direct_tool = FixedReadTool(_inspection())
    context = ProcessorAgentContext(
        canonical_commit=TEST_COMMIT,
        authority_instance="unit-test-authority",
    )
    core = ProcessorAgentCore(direct_tool, context=context)
    direct = core.inspect()
    facade = run_processor_pilot(
        FixedReadTool(_inspection()),
        canonical_commit=TEST_COMMIT,
        authority_instance="unit-test-authority",
    )

    assert direct_tool.calls == 1
    assert canonical_json(direct.public()) == canonical_json(facade.public())
    with pytest.raises(ProcessorPilotError, match="processor_core_already_completed"):
        core.inspect()
    assert direct_tool.calls == 1


def test_unexpected_read_result_fails_closed_after_one_call() -> None:
    tool = FixedReadTool(object())
    core = ProcessorAgentCore(
        tool,
        context=ProcessorAgentContext(canonical_commit=TEST_COMMIT),
    )

    with pytest.raises(TypeError, match="ProcessorInspection"):
        core.inspect()
    with pytest.raises(ProcessorPilotError, match="processor_core_already_completed"):
        core.inspect()
    assert tool.calls == 1


@pytest.mark.parametrize(
    ("inspection", "primary_code", "mutation_class", "approval_requirement"),
    [
        (
            _inspection(
                eligible_count=0,
                missing_count=0,
                prepared_count=0,
                complete_count=0,
            ),
            "PROCESSOR_CONVERGED",
            MutationClass.READ_ONLY,
            ApprovalRequirement.NONE,
        ),
        (
            _inspection(
                eligible_count=1,
                missing_count=1,
                prepared_count=0,
                complete_count=0,
            ),
            "PROCESSOR_MISSING_BACKLOG",
            MutationClass.PROPOSAL_ONLY,
            ApprovalRequirement.NONE,
        ),
        (
            _inspection(
                eligible_count=1,
                missing_count=0,
                prepared_count=1,
                complete_count=0,
            ),
            "PROCESSOR_PREPARED_BACKLOG",
            MutationClass.PROPOSAL_ONLY,
            ApprovalRequirement.NONE,
        ),
        (
            _inspection(
                eligible_count=1,
                missing_count=0,
                prepared_count=0,
                complete_count=1,
                deferred_lock_count=1,
            ),
            "PROCESSOR_DEFERRED_BUSY",
            MutationClass.READ_ONLY,
            ApprovalRequirement.NONE,
        ),
        (
            _inspection(
                eligible_count=0,
                missing_count=0,
                prepared_count=0,
                complete_count=0,
                identity_conflict_count=1,
            ),
            "PROCESSOR_IDENTITY_CONFLICT",
            MutationClass.ESCALATION_ONLY,
            ApprovalRequirement.SEPARATE_DESIGN_AUTHORITY,
        ),
        (
            _inspection(
                eligible_count=0,
                missing_count=0,
                prepared_count=0,
                complete_count=0,
                integrity_status=ProcessorIntegrityStatus.FAIL,
            ),
            "PROCESSOR_INTEGRITY_FAILURE",
            MutationClass.ESCALATION_ONLY,
            ApprovalRequirement.SEPARATE_DESIGN_AUTHORITY,
        ),
    ],
)
def test_core_preserves_classification_and_displays_exact_proposal_requirement(
    inspection: ProcessorInspection,
    primary_code: str,
    mutation_class: MutationClass,
    approval_requirement: ApprovalRequirement,
) -> None:
    result = ProcessorAgentCore(
        FixedReadTool(inspection),
        context=ProcessorAgentContext(canonical_commit=TEST_COMMIT),
    ).inspect()

    assert result.classification.primary_code == primary_code
    assert result.proposal.mutation_class is mutation_class
    assert result.proposal_requirement is approval_requirement
    assert result.proposal_requirement is result.proposal.approval_requirement
    assert result.receipt.final_status is ReceiptStatus.READ_ONLY_COMPLETE
    assert result.receipt.approval_sha256 is None
    assert result.receipt.execution_sha256 is None
    assert result.receipt.verification_sha256 is None
    rendered = canonical_json(result.public())
    assert f'"approval_requirement":"{approval_requirement.value}"' in rendered
    assert "INVOKE_PROCESSOR_WORKER_RUN" not in rendered


def test_well_formed_wrong_canonical_commit_is_rejected_before_read() -> None:
    tool = FixedReadTool(_inspection())
    with pytest.raises(ProcessorPilotError, match="canonical_commit_mismatch"):
        run_processor_pilot(tool, canonical_commit=WRONG_COMMIT)
    assert tool.calls == 0


def test_direct_context_rejects_bad_application_binding_before_read() -> None:
    with pytest.raises(ProcessorPilotError, match="canonical_commit_mismatch"):
        ProcessorAgentContext(canonical_commit=WRONG_COMMIT)
    with pytest.raises(ProcessorPilotError, match="authority_instance_invalid"):
        ProcessorAgentContext(
            canonical_commit=TEST_COMMIT,
            authority_instance="contains-password",
        )


def test_unresolved_product_provenance_is_rejected_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pilot_module,
        "_EXPECTED_CANONICAL_COMMIT",
        "not-a-public-commit",
    )
    tool = FixedReadTool(_inspection())
    with pytest.raises(ProcessorPilotError, match="product_provenance_unresolved"):
        run_processor_pilot(tool, canonical_commit=TEST_COMMIT)
    assert tool.calls == 0


def test_mismatched_base_product_provenance_is_rejected_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        processor_product_provenance,
        "CANONICAL_COMMIT",
        WRONG_COMMIT,
    )
    tool = FixedReadTool(_inspection())
    with pytest.raises(
        ProcessorPilotError,
        match="base_product_provenance_mismatch",
    ):
        run_processor_pilot(tool, canonical_commit=TEST_COMMIT)
    assert tool.calls == 0


def test_unresolved_base_product_provenance_is_rejected_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        processor_product_provenance,
        "CANONICAL_COMMIT",
        "not-a-public-commit",
    )
    tool = FixedReadTool(_inspection())
    with pytest.raises(
        ProcessorPilotError,
        match="base_product_provenance_unresolved",
    ):
        run_processor_pilot(tool, canonical_commit=TEST_COMMIT)
    assert tool.calls == 0


def test_sqlite_tool_reads_schema10_without_changing_directory_inventory(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    migrations.migrate(database)
    before = _directory_inventory(tmp_path)

    result = run_processor_pilot(
        SQLiteProcessorReadTool(database),
        canonical_commit=TEST_COMMIT,
        authority_instance="unit-test-authority",
    )

    after = _directory_inventory(tmp_path)
    assert before == after
    assert result.observation.authority.database_schema_version == 10
    assert result.observation.eligible_count == 0
    assert result.classification.primary_code == "PROCESSOR_CONVERGED"
    assert result.receipt.final_status is ReceiptStatus.READ_ONLY_COMPLETE


@pytest.mark.parametrize("version", [8, 9])
def test_schema8_and_schema9_authority_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: int,
) -> None:
    database = tmp_path / f"authority-v{version}.sqlite3"
    _migrate_to(database, version, monkeypatch)
    before = _directory_inventory(tmp_path)

    with pytest.raises(ProcessorPilotError, match="database_schema_unsupported"):
        SQLiteProcessorReadTool(database).inspect()

    assert _directory_inventory(tmp_path) == before


def test_malformed_migration_history_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "malformed.sqlite3"
    migrations.migrate(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE schema_migrations SET name = ? WHERE version = 10",
            ("not-canonical",),
        )
    before = _directory_inventory(tmp_path)

    with pytest.raises(ProcessorPilotError, match="database_migration_required"):
        SQLiteProcessorReadTool(database).inspect()

    assert _directory_inventory(tmp_path) == before


def test_missing_database_is_unavailable_and_is_not_created(tmp_path: Path) -> None:
    database = tmp_path / "missing.sqlite3"
    before = _directory_inventory(tmp_path)

    with pytest.raises(ProcessorPilotError, match="database_unavailable"):
        SQLiteProcessorReadTool(database).inspect()

    assert not database.exists()
    assert _directory_inventory(tmp_path) == before


def test_inspection_rejects_incoherent_pass_counts() -> None:
    with pytest.raises(
        ValueError,
        match="processor inspection state counts must equal eligible_count",
    ):
        _inspection(
            eligible_count=2,
            missing_count=1,
            prepared_count=0,
            complete_count=0,
        )


def test_inspection_rejects_unobserved_or_wrong_schema_version() -> None:
    for version in (0, 8, 9, 11):
        with pytest.raises(
            ValueError,
            match="processor inspection requires observed database schema version 10",
        ):
            _inspection(database_schema_version=version)
