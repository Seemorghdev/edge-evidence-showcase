#!/usr/bin/env python3
"""Offline non-authoritative demonstration of the exported read-only ADK tool."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from google.adk.tools import ToolContext

from apps.processor_pilot import (
    ProcessorAgentContext,
    ProcessorAgentCore,
    ProcessorInspection,
)
from apps.processor_pilot.adk_adapter import build_processor_adk_tool
from packages.agent_contracts.canonical import canonical_json

COMMIT = "0000000000000000000000000000000000000000"


class DemoReadTool:
    def __init__(self) -> None:
        self.calls = 0

    def inspect(self) -> ProcessorInspection:
        self.calls += 1
        return ProcessorInspection(
            database_schema_version=10,
            eligible_count=5,
            missing_count=0,
            prepared_count=1,
            complete_count=4,
        )


def main() -> int:
    read_tool = DemoReadTool()
    context = ProcessorAgentContext(
        canonical_commit=COMMIT,
        authority_instance="exported-offline-adk-demo",
    )
    core = ProcessorAgentCore(read_tool, context=context)
    tool = build_processor_adk_tool(core)
    tool_context = MagicMock(spec_set=ToolContext)

    result = asyncio.run(
        tool.run_async(args={}, tool_context=tool_context)
    )
    if read_tool.calls != 1:
        raise AssertionError("demo must perform exactly one read-only inspection")

    receipt = {
        "status": "pass",
        "proof_class": "standalone_offline_read_only_processor_adk",
        "model_provider_used": False,
        "credentials_used": False,
        "worker_invoked": False,
        "mutation_performed": False,
        "model_prose_authoritative": False,
        "tool_invocations": read_tool.calls,
        "classification": result["classification"]["primary_code"],
        "final_status": result["receipt"]["final_status"],
    }
    print(canonical_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
