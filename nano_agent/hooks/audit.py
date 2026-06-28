from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from pydantic import BaseModel

from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.models import ApprovalLevel, ToolUseRequest
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult


class ToolAuditRecord(BaseModel):
    """One replayable summary of a completed tool call."""

    timestamp: datetime  # 工具调用审计记录的写入时间。
    run_id: str  # 调用所属的 Agent 运行标识。
    llm_call_id: str | None  # 发起本次工具调用的 LLM 调用标识。
    step: int  # 工具调用发生时的 Agent loop 步骤。
    tool_call_id: str  # LLM 为本次工具调用生成的标识。
    tool_name: str  # 被调用的工具名称。
    approval_level: ApprovalLevel  # 本次工具调用对应的权限等级。
    input_summary: str  # 经过脱敏和截断的工具输入摘要。
    success: bool  # 工具是否成功完成。
    summary: str  # 工具返回的结果摘要。
    error_code: str | None  # 工具失败时的稳定错误码。
    error_message: str | None  # 工具失败时的错误说明。
    duration_seconds: float  # 工具调用耗时。


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

    async def after_tool_call(
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
            llm_call_id=context.current_llm_call_id,
            step=context.current_step,
            tool_call_id=tool_use.id,
            tool_name=tool.name,
            approval_level=tool.approval_level,
            input_summary=self._input_summary(tool.audit_input(tool_use.input)),
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
                file.flush()
                os.fsync(file.fileno())
        except OSError as exc:
            self._write_errors.append(str(exc))
        return None

    def _input_summary(self, input_data: dict) -> str:
        serialized = json.dumps(input_data, ensure_ascii=False, sort_keys=True)
        if len(serialized) <= self.max_input_chars:
            return serialized
        marker = "...[truncated]"
        return serialized[: self.max_input_chars - len(marker)] + marker
