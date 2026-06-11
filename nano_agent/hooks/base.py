from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from nano_agent.models import AgentMessage, LLMResponse, ToolUseRequest
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult, ToolSpec


class HookResult(BaseModel):
    """Non-blocking output produced by a hook callback."""

    injected_messages: list[AgentMessage] = Field(default_factory=list)


class AgentHook(Protocol):
    """Agent loop 扩展点协议，用于权限、审计、错误恢复等机制。"""

    def before_llm_call(
        self,
        context: ToolContext,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> HookResult | None:
        """LLM 调用前触发。"""

    def after_llm_call(
        self,
        context: ToolContext,
        response: LLMResponse,
    ) -> HookResult | None:
        """LLM 调用后触发。"""

    def before_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
    ) -> HookResult | None:
        """工具调用前触发。"""

    def after_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
        result: ToolResult,
        duration_seconds: float,
    ) -> HookResult | None:
        """工具调用后触发。"""

    def on_error(self, context: ToolContext, error: Exception) -> HookResult | None:
        """Agent loop 捕获错误时触发。"""


class NoOpHook:
    """默认空 hook，提供可选扩展点的稳定实现。"""

    def before_llm_call(
        self,
        context: ToolContext,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> HookResult | None:
        return None

    def after_llm_call(
        self,
        context: ToolContext,
        response: LLMResponse,
    ) -> HookResult | None:
        return None

    def before_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
    ) -> HookResult | None:
        return None

    def after_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
        result: ToolResult,
        duration_seconds: float,
    ) -> HookResult | None:
        return None

    def on_error(self, context: ToolContext, error: Exception) -> HookResult | None:
        return None
