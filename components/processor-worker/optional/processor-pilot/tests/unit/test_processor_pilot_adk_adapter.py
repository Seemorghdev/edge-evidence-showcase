"""Tests for the optional PRA-P02A read-only ADK adapter."""

from __future__ import annotations

import asyncio
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import importlib
import importlib.abc
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import threading
import uuid
from unittest.mock import MagicMock

import pytest

from apps.processor_pilot import (
    ProcessorAgentContext,
    ProcessorAgentCore,
    ProcessorInspection,
    ProcessorPilotError,
)
from apps.processor_pilot import pilot as pilot_module
from apps.processor_worker import provenance as processor_product_provenance
from packages.agent_contracts.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[2]
TEST_COMMIT = "a" * 40
POSITIVE_MARKER = pytest.mark.pra_p02a_adk_positive


@pytest.fixture(autouse=True)
def _bind_test_product_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pilot_module, "_EXPECTED_CANONICAL_COMMIT", TEST_COMMIT)
    monkeypatch.setattr(
        processor_product_provenance,
        "CANONICAL_COMMIT",
        TEST_COMMIT,
    )


def _inspection() -> ProcessorInspection:
    return ProcessorInspection(
        database_schema_version=10,
        eligible_count=2,
        missing_count=1,
        prepared_count=0,
        complete_count=1,
    )


class FixedReadTool:
    def __init__(self, inspection: object | None = None) -> None:
        self.inspection = inspection if inspection is not None else _inspection()
        self.calls = 0

    def inspect(self) -> object:
        self.calls += 1
        return self.inspection


def _core(read_tool: object | None = None) -> ProcessorAgentCore:
    return ProcessorAgentCore(
        read_tool if read_tool is not None else FixedReadTool(),  # type: ignore[arg-type]
        context=ProcessorAgentContext(
            canonical_commit=TEST_COMMIT,
            authority_instance="pra-p02a-test-authority",
        ),
    )


def _positive_api():
    try:
        from google.adk.tools import FunctionTool, ToolContext
    except ModuleNotFoundError as exc:
        if os.environ.get("PRA_P02A_ADK_REQUIRED") == "1":
            raise
        if exc.name in {"google", "google.adk"}:
            pytest.skip("google-adk optional dependency is not installed")
        raise

    adapter = importlib.import_module("apps.processor_pilot.adk_adapter")
    return adapter, FunctionTool, ToolContext


def _tool_context():
    _, _, ToolContext = _positive_api()
    return MagicMock(spec_set=ToolContext)


def _error_code(error: BaseException, expected: str) -> None:
    assert isinstance(error, ProcessorPilotError)
    assert error.finding == expected
    assert str(error) == expected


def _mock_snapshot(mock: MagicMock) -> tuple[object, ...]:
    return (
        tuple(mock.mock_calls),
        tuple(
            sorted(
                (name, id(child))
                for name, child in mock._mock_children.items()  # type: ignore[attr-defined]
            )
        ),
        tuple(sorted((name, id(value)) for name, value in vars(mock).items())),
    )


def _adk_is_installed() -> bool:
    try:
        return importlib.util.find_spec("google.adk") is not None
    except ModuleNotFoundError:
        return False


def test_package_and_cli_import_without_adk() -> None:
    assert not _adk_is_installed()
    package = importlib.import_module("apps.processor_pilot")
    cli = importlib.import_module("apps.processor_pilot.cli")

    assert callable(package.run_processor_pilot)
    assert callable(cli.main)
    assert "apps.processor_pilot.adk_adapter" not in sys.modules


def test_explicit_adapter_import_reports_exact_missing_extra_without_adk() -> None:
    assert not _adk_is_installed()
    sys.modules.pop("apps.processor_pilot.adk_adapter", None)

    with pytest.raises(ProcessorPilotError) as captured:
        importlib.import_module("apps.processor_pilot.adk_adapter")

    _error_code(captured.value, "processor_adk_extra_required")
    assert isinstance(captured.value.__cause__, ModuleNotFoundError)
    assert captured.value.__cause__.name in {"google", "google.adk"}
    assert "apps.processor_pilot.adk_adapter" not in sys.modules


@POSITIVE_MARKER
def test_builds_one_strict_zero_argument_tool() -> None:
    adapter, FunctionTool, _ = _positive_api()
    tool = adapter.build_processor_adk_tool(_core())

    assert isinstance(tool, FunctionTool)
    assert type(tool).__name__ == "_StrictZeroArgumentFunctionTool"
    assert tool.name == adapter.PROCESSOR_ADK_TOOL_NAME
    assert tool.name == "inspect_processor_authority"
    assert tuple(inspect.signature(tool.func).parameters) == ()
    assert tool._require_confirmation is False

    declaration = tool._get_declaration()
    assert declaration is not None
    declaration_payload = declaration.model_dump()
    assert declaration_payload.get("parameters") is None
    assert declaration_payload.get("parameters_json_schema") is None
    semantic_parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    assert semantic_parameters == {
        "type": "object",
        "properties": {},
        "required": [],
    }


@POSITIVE_MARKER
def test_empty_arguments_run_async_matches_separate_direct_core() -> None:
    adapter, _, _ = _positive_api()
    read_tool = FixedReadTool()
    tool = adapter.build_processor_adk_tool(_core(read_tool))
    direct_core = _core(FixedReadTool())
    expected = json.loads(canonical_json(direct_core.inspect().public()))

    result = asyncio.run(
        tool.run_async(args={}, tool_context=_tool_context())
    )

    assert result == expected
    assert read_tool.calls == 1
    assert set(result) == {
        "schema",
        "observation",
        "classification",
        "explanation",
        "proposal",
        "receipt",
    }
    assert result["schema"] == "processor-readonly-pilot-result.v1"
    assert result["receipt"]["final_status"] == "read-only-complete"
    assert result["receipt"]["approval_sha256"] is None
    assert result["receipt"]["execution_sha256"] is None
    assert result["receipt"]["verification_sha256"] is None
    rendered = canonical_json(result).lower()
    for forbidden in (
        "database_path",
        "credential",
        "prompt",
        "session",
        "model_prose",
    ):
        assert forbidden not in rendered


@POSITIVE_MARKER
def test_nonempty_arguments_raise_exact_error_before_claim() -> None:
    adapter, _, _ = _positive_api()
    read_tool = FixedReadTool()
    tool = adapter.build_processor_adk_tool(_core(read_tool))
    context = _tool_context()
    before = _mock_snapshot(context)

    with pytest.raises(ProcessorPilotError) as captured:
        asyncio.run(
            tool.run_async(
                args={"ignored": True},
                tool_context=context,
            )
        )

    _error_code(captured.value, "processor_adk_arguments_forbidden")
    assert read_tool.calls == 0
    assert _mock_snapshot(context) == before

    result = asyncio.run(tool.run_async(args={}, tool_context=_tool_context()))
    assert result["schema"] == "processor-readonly-pilot-result.v1"
    assert read_tool.calls == 1


@POSITIVE_MARKER
def test_sequential_second_invocation_fails_exactly() -> None:
    adapter, _, _ = _positive_api()
    read_tool = FixedReadTool()
    tool = adapter.build_processor_adk_tool(_core(read_tool))

    asyncio.run(tool.run_async(args={}, tool_context=_tool_context()))
    with pytest.raises(ProcessorPilotError) as captured:
        asyncio.run(tool.run_async(args={}, tool_context=_tool_context()))

    _error_code(captured.value, "processor_core_already_completed")
    assert read_tool.calls == 1


@POSITIVE_MARKER
def test_post_claim_failure_remains_consumed() -> None:
    adapter, _, _ = _positive_api()
    sentinel = RuntimeError("post-claim-read-failure")

    class FailingReadTool:
        calls = 0

        def inspect(self) -> object:
            self.calls += 1
            raise sentinel

    read_tool = FailingReadTool()
    tool = adapter.build_processor_adk_tool(_core(read_tool))

    with pytest.raises(RuntimeError) as first:
        asyncio.run(tool.run_async(args={}, tool_context=_tool_context()))
    assert first.value is sentinel

    with pytest.raises(ProcessorPilotError) as second:
        asyncio.run(tool.run_async(args={}, tool_context=_tool_context()))
    _error_code(second.value, "processor_core_already_completed")
    assert read_tool.calls == 1


@POSITIVE_MARKER
def test_reentrant_invocation_fails_without_deadlock() -> None:
    adapter, _, _ = _positive_api()

    class ReentrantReadTool:
        def __init__(self) -> None:
            self.calls = 0
            self.tool = None
            self.errors: list[BaseException] = []

        def inspect(self) -> ProcessorInspection:
            self.calls += 1

            def invoke_again() -> None:
                try:
                    asyncio.run(
                        self.tool.run_async(  # type: ignore[union-attr]
                            args={},
                            tool_context=_tool_context(),
                        )
                    )
                except BaseException as exc:
                    self.errors.append(exc)

            thread = threading.Thread(target=invoke_again)
            thread.start()
            thread.join(timeout=5)
            assert not thread.is_alive()
            return _inspection()

    read_tool = ReentrantReadTool()
    tool = adapter.build_processor_adk_tool(_core(read_tool))
    read_tool.tool = tool

    result = asyncio.run(tool.run_async(args={}, tool_context=_tool_context()))

    assert result["schema"] == "processor-readonly-pilot-result.v1"
    assert read_tool.calls == 1
    assert len(read_tool.errors) == 1
    _error_code(read_tool.errors[0], "processor_core_already_completed")


@POSITIVE_MARKER
def test_two_synchronized_invocations_allow_one_core_entry() -> None:
    adapter, _, _ = _positive_api()

    class BlockingReadTool:
        def __init__(self) -> None:
            self.calls = 0
            self.entered = threading.Event()
            self.release = threading.Event()

        def inspect(self) -> ProcessorInspection:
            self.calls += 1
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise RuntimeError("concurrent test release timeout")
            return _inspection()

    read_tool = BlockingReadTool()
    tool = adapter.build_processor_adk_tool(_core(read_tool))
    start = threading.Barrier(2)

    def invoke() -> dict[str, object]:
        start.wait(timeout=5)
        return asyncio.run(
            tool.run_async(args={}, tool_context=_tool_context())
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invoke) for _ in range(2)]
        try:
            assert read_tool.entered.wait(timeout=5)
            completed, _ = wait(
                futures,
                timeout=5,
                return_when=FIRST_COMPLETED,
            )
            assert len(completed) == 1
        finally:
            read_tool.release.set()

        outcomes: list[object] = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=5))
            except BaseException as exc:
                outcomes.append(exc)

    successes = [item for item in outcomes if isinstance(item, dict)]
    failures = [item for item in outcomes if isinstance(item, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    _error_code(failures[0], "processor_core_already_completed")
    assert read_tool.calls == 1


@POSITIVE_MARKER
def test_tool_context_double_is_neither_read_nor_mutated() -> None:
    adapter, _, _ = _positive_api()
    tool = adapter.build_processor_adk_tool(_core())
    context = _tool_context()
    before = _mock_snapshot(context)

    asyncio.run(tool.run_async(args={}, tool_context=context))

    assert _mock_snapshot(context) == before


def _is_affected_module(name: str) -> bool:
    return (
        name == "google"
        or name.startswith("google.")
        or name == "apps.processor_pilot.adk_adapter"
    )


class _ImportFaultFinder(importlib.abc.MetaPathFinder):
    def __init__(self, target: str, outcome: BaseException) -> None:
        self.target = target
        self.outcome = outcome
        self.requested: list[str] = []

    def find_spec(self, fullname, path=None, target=None):
        self.requested.append(fullname)
        if fullname == self.target:
            raise self.outcome
        return None


def _execute_adapter_with_import_fault(
    *,
    target: str,
    outcome: BaseException,
) -> tuple[BaseException | None, tuple[str, ...]]:
    modules_before = dict(sys.modules)
    affected_before = {
        name: module
        for name, module in modules_before.items()
        if _is_affected_module(name)
    }
    meta_path_before = tuple(sys.meta_path)
    importer_cache_before = dict(sys.path_importer_cache)

    for name in tuple(sys.modules):
        if _is_affected_module(name):
            del sys.modules[name]

    finder = _ImportFaultFinder(target, outcome)
    synthetic_name = (
        "apps.processor_pilot._pra_p02a_import_fault_"
        + uuid.uuid4().hex
    )
    adapter_path = (
        ROOT
        / "apps"
        / "processor_pilot"
        / "adk_adapter.py"
    )
    caught: BaseException | None = None

    try:
        sys.meta_path.insert(0, finder)
        spec = importlib.util.spec_from_file_location(
            synthetic_name,
            adapter_path,
        )
        if spec is None or spec.loader is None:
            raise AssertionError("adapter source has no executable loader")
        module = importlib.util.module_from_spec(spec)
        sys.modules[synthetic_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException as exc:
            caught = exc
    finally:
        for name in tuple(sys.modules):
            if name not in modules_before:
                del sys.modules[name]
        for name, module in modules_before.items():
            sys.modules[name] = module

        sys.meta_path[:] = list(meta_path_before)
        sys.path_importer_cache.clear()
        sys.path_importer_cache.update(importer_cache_before)

        assert set(sys.modules) == set(modules_before)
        assert all(
            sys.modules[name] is module
            for name, module in modules_before.items()
        )
        affected_after = {
            name: module
            for name, module in sys.modules.items()
            if _is_affected_module(name)
        }
        assert set(affected_after) == set(affected_before)
        assert all(
            affected_after[name] is module
            for name, module in affected_before.items()
        )
        assert len(sys.meta_path) == len(meta_path_before)
        assert all(
            current is original
            for current, original in zip(
                sys.meta_path,
                meta_path_before,
                strict=True,
            )
        )
        assert set(sys.path_importer_cache) == set(importer_cache_before)
        assert all(
            sys.path_importer_cache[key] is value
            for key, value in importer_cache_before.items()
        )

    if target not in finder.requested:
        raise AssertionError(f"fault target was not requested: {target}")
    return caught, tuple(finder.requested)


@POSITIVE_MARKER
def test_missing_google_namespace_maps_to_extra_required() -> None:
    _positive_api()
    injected = ModuleNotFoundError(name="google")

    caught, requested = _execute_adapter_with_import_fault(
        target="google",
        outcome=injected,
    )

    assert "google" in requested
    assert isinstance(caught, ProcessorPilotError)
    _error_code(caught, "processor_adk_extra_required")
    assert caught.__cause__ is injected


@POSITIVE_MARKER
def test_missing_google_adk_namespace_maps_to_extra_required() -> None:
    _positive_api()
    injected = ModuleNotFoundError(name="google.adk")

    caught, requested = _execute_adapter_with_import_fault(
        target="google.adk",
        outcome=injected,
    )

    assert "google.adk" in requested
    assert isinstance(caught, ProcessorPilotError)
    _error_code(caught, "processor_adk_extra_required")
    assert caught.__cause__ is injected


@POSITIVE_MARKER
def test_missing_google_adk_tools_propagates_unchanged() -> None:
    _positive_api()
    injected = ModuleNotFoundError(name="google.adk.tools")

    caught, requested = _execute_adapter_with_import_fault(
        target="google.adk.tools",
        outcome=injected,
    )

    assert "google.adk.tools" in requested
    assert caught is injected


@POSITIVE_MARKER
def test_missing_google_genai_propagates_unchanged() -> None:
    _positive_api()
    injected = ModuleNotFoundError(name="google.genai")

    caught, requested = _execute_adapter_with_import_fault(
        target="google.genai",
        outcome=injected,
    )

    assert "google.genai" in requested
    assert caught is injected


@POSITIVE_MARKER
def test_arbitrary_sdk_import_exception_propagates_unchanged() -> None:
    _positive_api()
    injected = RuntimeError("processor_adk_import_sentinel")

    caught, requested = _execute_adapter_with_import_fault(
        target="google.adk.tools",
        outcome=injected,
    )

    assert "google.adk.tools" in requested
    assert caught is injected