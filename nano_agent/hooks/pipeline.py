from __future__ import annotations

from nano_agent.hooks.base import AgentHook, HookResult
from nano_agent.models import AgentMessage, LLMResponse, ToolUseRequest
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult, ToolSpec


class HookPipeline:
    """Run agent hooks in a single ordered async execution chain.

    Each method appends injected messages directly into the caller-supplied
    target list so that hook output produced before an exception is not lost.
    """

    def __init__(self, hooks: list[AgentHook] | None = None) -> None:
        self.hooks = hooks or []  # Hook instances executed in registration order.

    async def before_llm_call(
        self,
        target: list[AgentMessage],
        context: ToolContext,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
    ) -> None:
        """Run pre-LLM hooks, appending messages to target before the LLM request."""
        for hook in self.hooks:
            self._extend(target, await hook.before_llm_call(context, messages, tools))

    async def after_llm_call(
        self,
        target: list[AgentMessage],
        context: ToolContext,
        response: LLMResponse,
    ) -> None:
        """Run post-LLM hooks, appending messages to target for deferred insertion."""
        for hook in self.hooks:
            self._extend(target, await hook.after_llm_call(context, response))

    async def before_tool_call(
        self,
        target: list[AgentMessage],
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
    ) -> None:
        """Run pre-tool hooks, appending messages to target before tool invocation."""
        for hook in self.hooks:
            self._extend(target, await hook.before_tool_call(context, tool, tool_use))

    async def after_tool_call(
        self,
        target: list[AgentMessage],
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
        result: ToolResult,
        duration_seconds: float,
    ) -> None:
        """Run post-tool hooks, appending messages to target after tool execution."""
        for hook in self.hooks:
            self._extend(
                target,
                await hook.after_tool_call(
                    context,
                    tool,
                    tool_use,
                    result,
                    duration_seconds,
                ),
            )

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
