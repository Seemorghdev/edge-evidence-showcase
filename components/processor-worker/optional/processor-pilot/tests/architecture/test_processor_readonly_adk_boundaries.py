"""Architecture gates for the PRA-P02A read-only ADK adapter."""

from __future__ import annotations

import ast
import importlib
import inspect
import os
from pathlib import Path
import tomllib

import pytest

from apps.processor_pilot import (
    ProcessorAgentContext,
    ProcessorAgentCore,
    ProcessorInspection,
)
from apps.processor_pilot import pilot as pilot_module
from apps.processor_worker import provenance as processor_product_provenance

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "apps" / "processor_pilot" / "adk_adapter.py"
PACKAGE_INIT = ROOT / "apps" / "processor_pilot" / "__init__.py"
PACKAGE_CLI = ROOT / "apps" / "processor_pilot" / "cli.py"
PYPROJECT = ROOT / "pyproject.toml"
TEST_COMMIT = "a" * 40


@pytest.fixture(autouse=True)
def _bind_test_product_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pilot_module, "_EXPECTED_CANONICAL_COMMIT", TEST_COMMIT)
    monkeypatch.setattr(
        processor_product_provenance,
        "CANONICAL_COMMIT",
        TEST_COMMIT,
    )


class FixedReadTool:
    def __init__(self) -> None:
        self.calls = 0

    def inspect(self) -> ProcessorInspection:
        self.calls += 1
        return ProcessorInspection(
            database_schema_version=10,
            eligible_count=0,
            missing_count=0,
            prepared_count=0,
            complete_count=0,
        )


def _positive_api():
    try:
        from google.adk.tools import FunctionTool
    except ModuleNotFoundError as exc:
        if os.environ.get("PRA_P02A_ADK_REQUIRED") == "1":
            raise
        if exc.name in {"google", "google.adk"}:
            pytest.skip("google-adk optional dependency is not installed")
        raise

    adapter = importlib.import_module("apps.processor_pilot.adk_adapter")
    return adapter, FunctionTool


def test_adapter_source_preserves_optional_readonly_boundary() -> None:
    source = ADAPTER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ADAPTER))

    assert "class _StrictZeroArgumentFunctionTool" in source
    assert "processor_adk_arguments_forbidden" in source
    assert "processor_core_already_completed" in source
    assert "json.loads(canonical_json(core.inspect().public()))" in source
    assert "require_confirmation=False" in source
    assert "ToolContext" not in source

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    allowed_imports = {
        "__future__",
        "json",
        "threading",
        "typing",
        "google.adk.tools",
        "packages.agent_contracts.canonical",
        "pilot",
    }
    assert imports <= allowed_imports

    lowered = source.lower()
    for forbidden in (
        "apps.processor_mutation",
        "apps.processor_worker",
        "run_exact",
        "agent(",
        "runner(",
        "session(",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "pathlib",
        "open(",
        "write_text",
        "write_bytes",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "terraform",
        "iam",
        "deployment",
        "publication",
        "memory_service",
        "artifact_service",
    ):
        assert forbidden not in lowered

    core_inspections = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "inspect"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "core"
    ]
    assert len(core_inspections) == 1
    assert not any(
        isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        for node in ast.walk(tree)
    )


def test_offline_demo_preserves_one_call_non_authoritative_boundary() -> None:
    public_root = (
        ROOT / "exports" / "processor-worker" / "public"
        if (ROOT / "exports" / "processor-worker" / "public").is_dir()
        else ROOT.parents[1]
    )
    demo = public_root / "demo" / "run_pilot_adk_demo.py"
    source = demo.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(demo))

    ordering = (
        "read_tool = DemoReadTool()",
        "context = ProcessorAgentContext(",
        "core = ProcessorAgentCore(read_tool, context=context)",
        "tool = build_processor_adk_tool(core)",
        "tool.run_async(args={}, tool_context=tool_context)",
    )
    offsets = [source.index(item) for item in ordering]
    assert offsets == sorted(offsets)
    assert source.count("tool.run_async(") == 1

    lowered = source.lower()
    for forbidden in (
        "agent(",
        "runner(",
        "session(",
        "google.generativeai",
        "google.genai",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "sqlite3",
        "run_exact",
        "processor-worker",
        "write_text",
        "write_bytes",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "terraform",
        "deployment",
        "publication",
        "memory_service",
        "artifact_service",
    ):
        assert forbidden not in lowered

    assert not any(
        isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        for node in ast.walk(tree)
    )


def test_adk_dependency_and_default_imports_remain_optional() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = pyproject["project"]
    extras = project["optional-dependencies"]

    if (ROOT / "exports" / "processor-worker" / "export.toml").is_file():
        assert project["dependencies"] == []
    else:
        assert project["dependencies"] == [
            "edge-evidence-processor-worker==0.1.0"
        ]
    assert extras["adk"] == ["google-adk==2.6.2"]
    assert "gcp" not in extras["adk"][0]
    assert (
        "pra_p02a_adk_positive: requires the isolated google-adk test environment"
        in pyproject["tool"]["pytest"]["ini_options"]["markers"]
    )

    for path in (PACKAGE_INIT, PACKAGE_CLI):
        text = path.read_text(encoding="utf-8").lower()
        assert "google.adk" not in text
        assert "adk_adapter" not in text


@pytest.mark.pra_p02a_adk_positive
def test_installed_adapter_exposes_only_one_model_facing_tool() -> None:
    adapter, FunctionTool = _positive_api()
    read_tool = FixedReadTool()
    core = ProcessorAgentCore(
        read_tool,
        context=ProcessorAgentContext(
            canonical_commit=TEST_COMMIT,
            authority_instance="pra-p02a-architecture-test",
        ),
    )
    tool = adapter.build_processor_adk_tool(core)

    assert isinstance(tool, FunctionTool)
    assert tool.name == "inspect_processor_authority"
    assert tuple(inspect.signature(tool.func).parameters) == ()
    assert adapter.__all__ == [
        "PROCESSOR_ADK_TOOL_NAME",
        "build_processor_adk_tool",
    ]

    local_tool_classes = [
        value
        for value in vars(adapter).values()
        if inspect.isclass(value)
        and issubclass(value, FunctionTool)
        and value.__module__ == adapter.__name__
    ]
    assert [value.__name__ for value in local_tool_classes] == [
        "_StrictZeroArgumentFunctionTool"
    ]

    for forbidden_name in (
        "Agent",
        "Runner",
        "Session",
        "ToolContext",
        "MemoryService",
        "ArtifactService",
        "Executor",
        "Worker",
    ):
        assert not hasattr(adapter, forbidden_name)
