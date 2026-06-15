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
                    "Inspect available tool schemas before acting. Prefer grep for text or "
                    "symbol search, then use read_file with a returned byte offset or an "
                    "explicit line_start/line_end range for bounded inspection. Do not call "
                    "run_command with grep, sed, awk, find, "
                    "cat, pwd, or Python search scripts when structured tools cover the work. "
                    "After a rejected operation, change strategy instead of retrying it. "
                    "Do not delegate to another agent. Do not claim actions or evidence you "
                    "did not observe. In finish_run, make resolution a self-contained statement "
                    "of the actual findings, not a statement that a summary was generated. Put "
                    "supporting evidence in verification_summary and preserve material risks. "
                    "Finish by calling finish_run as the only tool call."
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
