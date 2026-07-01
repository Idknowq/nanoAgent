from __future__ import annotations

from nano_agent.models import AgentMessage
from nano_agent.prompts.assembler import PromptTemplateLoader
from nano_agent.subagents.models import SubagentRequest


class SubagentContextBuilder:
    """Build a child conversation without copying the parent's transcript."""

    def __init__(self, loader: PromptTemplateLoader | None = None) -> None:
        self.loader = loader or PromptTemplateLoader()  # 读取子 Agent system prompt 模板。

    def build(self, request: SubagentRequest) -> list[AgentMessage]:
        messages = [
            AgentMessage(
                role="system",
                content=self.loader.load("subagent.md"),
            )
        ]
        if request.context:
            messages.append(
                AgentMessage(
                    role="system",
                    content=(
                        "<delegated_context>\n"
                        f"{request.context.strip()}\n"
                        "</delegated_context>"
                    ),
                )
            )
        messages.append(
            AgentMessage(
                role="user",
                content=f"<delegated_task>\n{request.task.strip()}\n</delegated_task>",
            )
        )
        return messages
