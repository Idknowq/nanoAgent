from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import BaseModel

from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.models import ApprovalLevel, ToolUseRequest
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult


class ToolAuditRecord(BaseModel):
    """One replayable summary of a completed tool call."""

    timestamp: datetime
    run_id: str
    step: int
    tool_call_id: str
    tool_name: str
    approval_level: ApprovalLevel
    input_summary: str
    success: bool
    summary: str
    error_code: str | None
    error_message: str | None
    duration_seconds: float


class AuditHook(NoOpHook):
    """Append completed tool calls to the current run's audit JSONL file."""

    def __init__(self, max_input_chars: int = 4_000) -> None:
        if max_input_chars < 100:
            raise ValueError("max_input_chars must be at least 100")
        self.max_input_chars = max_input_chars
        self._write_errors: list[str] = []

    @property
    def write_errors(self) -> list[str]:
        return list(self._write_errors)

    def after_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
        result: ToolResult,
        duration_seconds: float,
    ) -> HookResult | None:
        record = ToolAuditRecord(
            timestamp=datetime.now(timezone.utc),
            run_id=context.run_id,
            step=context.current_step,
            tool_call_id=tool_use.id,
            tool_name=tool.name,
            approval_level=tool.approval_level,
            input_summary=self._input_summary(tool_use.input),
            success=result.success,
            summary=result.summary,
            error_code=result.error_code,
            error_message=result.error_message,
            duration_seconds=duration_seconds,
        )
        try:
            context.run_dir.mkdir(parents=True, exist_ok=True)
            audit_path = context.run_dir / "audit.jsonl"
            line = record.model_dump_json() + "\n"
            with audit_path.open("a", encoding="utf-8") as file:
                file.write(line)
        except OSError as exc:
            self._write_errors.append(str(exc))
        return None

    def _input_summary(self, input_data: dict) -> str:
        serialized = json.dumps(input_data, ensure_ascii=False, sort_keys=True)
        if len(serialized) <= self.max_input_chars:
            return serialized
        marker = "...[truncated]"
        return serialized[: self.max_input_chars - len(marker)] + marker
