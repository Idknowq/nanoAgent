from __future__ import annotations

from nano_agent.hooks.base import AgentHook, HookResult
from nano_agent.models import AgentMessage, LLMResponse, ToolUseRequest
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult, ToolSpec


class HookPipeline:
    """Run agent hooks in a single ordered async execution chain."""

    def __init__(self, hooks: list[AgentHook] | None = None) -> None:
        self.hooks = hooks or []  # Hook instances executed in registration order.

    async def before_llm_call(
        self,
        context: ToolContext,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> list[AgentMessage]:
        """Run pre-LLM hooks and return messages that must enter the LLM request."""
        injected: list[AgentMessage] = []
        for hook in self.hooks:
            self._extend(injected, await hook.before_llm_call(context, messages, tools))
        return injected

    async def after_llm_call(
        self,
        context: ToolContext,
        response: LLMResponse,
    ) -> list[AgentMessage]:
        """Run post-LLM hooks and return messages deferred until protocol-safe insertion."""
        injected: list[AgentMessage] = []
        for hook in self.hooks:
            self._extend(injected, await hook.after_llm_call(context, response))
        return injected

    async def before_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
    ) -> list[AgentMessage]:
        """Run pre-tool hooks before invoking one runtime tool."""
        injected: list[AgentMessage] = []
        for hook in self.hooks:
            self._extend(injected, await hook.before_tool_call(context, tool, tool_use))
        return injected

    async def after_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
        result: ToolResult,
        duration_seconds: float,
    ) -> list[AgentMessage]:
        """Run post-tool hooks after one runtime tool has completed."""
        injected: list[AgentMessage] = []
        for hook in self.hooks:
            self._extend(
                injected,
                await hook.after_tool_call(
                    context,
                    tool,
                    tool_use,
                    result,
                    duration_seconds,
                ),
            )
        return injected

    async def on_error(self, context: ToolContext, error: Exception) -> None:
        """Notify hooks about an error without replacing the original exception."""
        for hook in self.hooks:
            try:
                await hook.on_error(context, error)
            except Exception:
                continue

    @staticmethod
    def _extend(target: list[AgentMessage], result: HookResult | None) -> None:
        """Append injected hook messages when a hook produced any."""
        if result is not None:
            target.extend(result.injected_messages)
