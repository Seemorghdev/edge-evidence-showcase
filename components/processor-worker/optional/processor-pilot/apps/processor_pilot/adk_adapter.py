"""Optional read-only Google ADK adapter for the processor pilot."""

from __future__ import annotations

import json
import threading
from typing import Any

try:
    from google.adk.tools import FunctionTool
except ModuleNotFoundError as exc:
    if exc.name in {"google", "google.adk"}:
        from .pilot import ProcessorPilotError

        raise ProcessorPilotError("processor_adk_extra_required") from exc
    raise

from packages.agent_contracts.canonical import canonical_json

from .pilot import ProcessorAgentCore, ProcessorPilotError

PROCESSOR_ADK_TOOL_NAME = "inspect_processor_authority"


class _StrictZeroArgumentFunctionTool(FunctionTool):
    """FunctionTool that accepts one valid empty-argument attempt."""

    def __init__(self, *, func: Any) -> None:
        super().__init__(func, require_confirmation=False)
        self._processor_claim_lock = threading.Lock()
        self._processor_consumed = False

    def _claim_once(self) -> None:
        with self._processor_claim_lock:
            if self._processor_consumed:
                raise ProcessorPilotError("processor_core_already_completed")
            self._processor_consumed = True

    async def run_async(
        self,
        *,
        args: dict[str, Any],
        tool_context: Any,
    ) -> Any:
        if not isinstance(args, dict) or args:
            raise ProcessorPilotError("processor_adk_arguments_forbidden")
        self._claim_once()
        return await super().run_async(
            args=args,
            tool_context=tool_context,
        )


def build_processor_adk_tool(
    core: ProcessorAgentCore,
) -> FunctionTool:
    """Build the sole read-only ADK tool over one configured core."""

    if not isinstance(core, ProcessorAgentCore):
        raise TypeError("processor ADK adapter requires ProcessorAgentCore")

    def inspect_processor_authority() -> dict[str, object]:
        """Inspect the configured processor authority exactly once."""

        return json.loads(canonical_json(core.inspect().public()))

    if inspect_processor_authority.__name__ != PROCESSOR_ADK_TOOL_NAME:
        raise RuntimeError("processor ADK tool name mismatch")

    return _StrictZeroArgumentFunctionTool(
        func=inspect_processor_authority,
    )


__all__ = [
    "PROCESSOR_ADK_TOOL_NAME",
    "build_processor_adk_tool",
]
