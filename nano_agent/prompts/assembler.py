from __future__ import annotations

from nano_agent.models import AgentMessage
from nano_agent.tools.base import ToolSpec


class PromptAssembler:
    """组装 Agent 初始消息，后续可接入 skills、memory 和策略提示词。"""

    def build_initial_messages(self, repo_url: str, tools: list[ToolSpec]) -> list[AgentMessage]:
        tool_names = ", ".join(tool.name for tool in tools)
        return [
            AgentMessage(
                role="system",
                content=(
                    "You are nanoAgent. Work in a loop: decide whether to call tools, "
                    "read tool results, then continue until you can end_turn. "
                    "Use bash as the primary execution tool. Use todo_write only when "
                    "a short-lived session task list is useful. "
                    f"Available tools: {tool_names}."
                ),
            ),
            AgentMessage(
                role="user",
                content=f"Analyze this GitHub repository and prepare for diagnosis: {repo_url}",
            ),
        ]
