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
                    "You are nanoAgent."
                    "Work in a loop: decide whether to call tools, "
                    "read tool results, then continue until you can end_turn. "
                    "Use clone_repo to clone the target repository. Use list_files and "
                    "read_file for repository inspection. Read a target file before editing "
                    "it, use edit_file only for exact minimal replacements, and run relevant "
                    "tests after editing. Use run_command only when a dedicated tool is "
                    "insufficient. Use todo_write only when a short-lived session task list "
                    "is useful."
                    "Fix bugs and rerun until it runs correctly. If fails, output with 'FAILED' on the begining."
                    f"Available tools: {tool_names}."
                ),
            ),
            AgentMessage(
                role="user",
                content=f"Analyze this GitHub repository and prepare for diagnosis: {repo_url}",
            ),
        ]
