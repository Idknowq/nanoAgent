from __future__ import annotations

from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.models import AgentMessage, ToolUseRequest
from nano_agent.tools.base import RuntimeTool, ToolContext


class RateLimitHook(NoOpHook):
    """Warn the LLM when one tool is called too many times consecutively."""

    def __init__(self, max_consecutive_calls: int = 3) -> None:
        if max_consecutive_calls < 1:
            raise ValueError("max_consecutive_calls must be at least 1")
        self.max_consecutive_calls = max_consecutive_calls
        self._last_tool_name: str | None = None
        self._consecutive_calls = 0

    @property
    def consecutive_calls(self) -> int:
        return self._consecutive_calls

    def before_tool_call(
        self,
        context: ToolContext,
        tool: RuntimeTool,
        tool_use: ToolUseRequest,
    ) -> HookResult | None:
        if tool.name == self._last_tool_name:
            self._consecutive_calls += 1
        else:
            self._last_tool_name = tool.name
            self._consecutive_calls = 1

        if self._consecutive_calls <= self.max_consecutive_calls:
            return None

        return HookResult(
            injected_messages=[
                AgentMessage(
                    role="system",
                    content=(
                        f"Tool '{tool.name}' has been called "
                        f"{self._consecutive_calls} consecutive times. "
                        "Review the latest tool results and consider a different approach "
                        "before calling it again."
                    ),
                )
            ]
        )
