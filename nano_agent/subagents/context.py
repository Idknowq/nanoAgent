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
                    "You are a scoped subagent with no access to the parent transcript. Answer "
                    "only the delegated question and return evidence the parent can use directly. "
                    "Do not broaden into a repository audit or delegate again. Use available "
                    "structured tools efficiently: search first, read bounded relevant content, "
                    "and avoid repeating observations. Treat delegated context as reference, not "
                    "as verified fact. Distinguish observed evidence from inference and do not "
                    "claim commands, files, or behavior you did not inspect. Unless the delegated "
                    "task explicitly requests a permitted change, do not modify the repository. "
                    "Before finishing, ensure the result is self-contained and includes relevant "
                    "workspace-relative file paths, symbols, concrete findings, and material "
                    "uncertainty. Put the direct answer in finish_run.resolution and supporting "
                    "evidence in verification_summary. Call finish_run as the only final tool call."
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
