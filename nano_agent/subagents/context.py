from __future__ import annotations

from nano_agent.models import AgentMessage
from nano_agent.subagents.models import SubagentRequest


class SubagentContextBuilder:
    """Build a child conversation without copying the parent's transcript."""

    def build(self, request: SubagentRequest) -> list[AgentMessage]:
        messages = [
            AgentMessage(
                role="system",
                content=(
                    "You are a scoped subagent. Work only on the delegated task using the "
                    "available tools. You do not have access to the parent conversation. "
                    "Do not delegate to another agent. Do not claim actions or evidence you "
                    "did not observe. Finish by calling finish_run as the only tool call."
                ),
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
