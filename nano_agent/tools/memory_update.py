"""Tool for the Agent to write and update persistent memories during a run."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

from nano_agent.memory.store import JsonlMemoryStore, MemoryRecord
from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import (
    RuntimeTool,
    ToolContext,
    ToolInput,
    ToolResult,
)


class MemoryUpdateInput(ToolInput):
    action: Literal["add", "upsert"]
    namespace: str
    key: str
    value: str
    tags: list[str] | None = None


class MemoryUpdateTool(RuntimeTool):
    name: ClassVar[str] = "memory_update"
    description: ClassVar[str] = (
        "Write or update a persistent memory record keyed by namespace + key. "
        "Use to preserve findings, failures, patterns, or preferences across runs. "
        "Use add for new records, upsert to overwrite an existing record."
    )
    approval_level: ClassVar[ApprovalLevel] = ApprovalLevel.WRITE
    input_model: ClassVar[type[MemoryUpdateInput]] = MemoryUpdateInput

    def run(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        parsed = MemoryUpdateInput.model_validate(input_data)
        memory_path = context.config.memory_path
        if memory_path is None:
            return ToolResult.failure(
                code="no_memory_path",
                message="memory_path is not configured in AgentConfig.",
            )
        store = JsonlMemoryStore(Path(memory_path))
        record = MemoryRecord(
            namespace=parsed.namespace,
            key=parsed.key,
            value=parsed.value,
            tags=parsed.tags or [],
        )
        try:
            if parsed.action == "add":
                store.add(record)
            else:
                store.upsert(record)
        except OSError as exc:
            return ToolResult.failure(
                code="memory_write_failed",
                message=f"Failed to write memory: {exc}",
            )
        return ToolResult(
            success=True,
            data={"namespace": parsed.namespace, "key": parsed.key},
            summary=f"Memory {parsed.action}ed: {parsed.namespace}/{parsed.key}",
        )
