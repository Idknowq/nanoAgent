from __future__ import annotations

import os
from datetime import datetime, timezone

from pydantic import BaseModel

from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.models import AgentMessage, LLMResponse
from nano_agent.tools.base import ToolContext, ToolSpec


class LLMCallRecord(BaseModel):
    """Metadata for one LLM request without duplicating conversation content."""

    schema_version: int = 1  # LLM 调用记录的数据结构版本。
    timestamp: datetime  # LLM 请求开始时间。
    run_id: str  # 调用所属的 Agent 运行标识。
    llm_call_id: str  # 当前运行内的 LLM 调用标识。
    step: int  # 调用发生时的 Agent loop 步骤。
    provider: str  # 实际使用的 LLM provider。
    model: str | None  # 实际使用的模型名称。
    duration_seconds: float  # LLM 请求耗时。
    success: bool  # LLM 请求是否成功返回。
    stop_reason: str | None  # 成功响应的停止原因。
    request_message_count: int  # 请求上下文中的消息数量。
    available_tool_count: int  # 请求中提供给模型的工具数量。
    requested_tool_call_count: int  # 响应中模型请求的工具调用数量。
    input_tokens: int | None  # 请求消耗的输入 token 数。
    output_tokens: int | None  # 响应生成的输出 token 数。
    total_tokens: int | None  # 本次调用消耗的 token 总数。
    cached_tokens: int | None  # 输入 token 中命中缓存的数量。
    error_type: str | None  # 失败时的异常类型。
    error_message: str | None  # 失败时的截断异常信息。


class LLMMetricsHook(NoOpHook):
    """Append one metadata record for every completed or failed LLM call."""

    def __init__(self) -> None:
        self._pending_call_id: str | None = None
        self._request_message_count = 0
        self._available_tool_count = 0
        self._write_errors: list[str] = []

    @property
    def write_errors(self) -> list[str]:
        return list(self._write_errors)

    def before_llm_call(
        self,
        context: ToolContext,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> HookResult | None:
        self._pending_call_id = context.current_llm_call_id
        self._request_message_count = len(messages)
        self._available_tool_count = len(tools)
        return None

    def after_llm_call(
        self,
        context: ToolContext,
        response: LLMResponse,
    ) -> HookResult | None:
        if self._pending_call_id is None:
            return None
        usage = response.usage
        self._write(
            context,
            LLMCallRecord(
                timestamp=context.current_llm_started_at or datetime.now(timezone.utc),
                run_id=context.run_id,
                llm_call_id=self._pending_call_id,
                step=context.current_step,
                provider=response.provider or context.config.llm_provider,
                model=response.model or context.config.llm_model,
                duration_seconds=context.current_llm_duration_seconds or 0.0,
                success=True,
                stop_reason=response.stop_reason,
                request_message_count=self._request_message_count,
                available_tool_count=self._available_tool_count,
                requested_tool_call_count=len(response.tool_uses),
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                cached_tokens=usage.cached_tokens if usage else None,
                error_type=None,
                error_message=None,
            ),
        )
        self._pending_call_id = None
        return None

    def on_error(self, context: ToolContext, error: Exception) -> HookResult | None:
        if self._pending_call_id is None:
            return None
        if context.current_llm_started_at is None:
            self._pending_call_id = None
            return None
        self._write(
            context,
            LLMCallRecord(
                timestamp=context.current_llm_started_at or datetime.now(timezone.utc),
                run_id=context.run_id,
                llm_call_id=self._pending_call_id,
                step=context.current_step,
                provider=context.config.llm_provider,
                model=context.config.llm_model,
                duration_seconds=context.current_llm_duration_seconds or 0.0,
                success=False,
                stop_reason=None,
                request_message_count=self._request_message_count,
                available_tool_count=self._available_tool_count,
                requested_tool_call_count=0,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                cached_tokens=None,
                error_type=type(error).__name__,
                error_message=str(error)[:2_000],
            ),
        )
        self._pending_call_id = None
        return None

    def _write(self, context: ToolContext, record: LLMCallRecord) -> None:
        try:
            context.run_dir.mkdir(parents=True, exist_ok=True)
            with (context.run_dir / "llm_calls.jsonl").open("a", encoding="utf-8") as file:
                file.write(record.model_dump_json() + "\n")
                file.flush()
                os.fsync(file.fileno())
        except OSError as exc:
            self._write_errors.append(str(exc))
