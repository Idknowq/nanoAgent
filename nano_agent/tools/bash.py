from __future__ import annotations

import subprocess
import time
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult, register_tool_factory


class BashTool(RuntimeTool):
    """核心 bash 工具，允许 Agent 在受控工作目录中执行 shell 命令。"""

    name = "bash"
    description = "Run a bash command in the current agent workspace."
    approval_level = ApprovalLevel.EXECUTE_RISKY
    category = "execution"
    requires_workspace = True
    is_mutating = True
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Bash command to run in the current workspace.",
            }
        },
        "required": ["command"],
    }

    def __init__(self, config: AgentConfig, cwd: Path) -> None:
        self.config = config  # 保存命令超时和输出截断配置。
        self.cwd = cwd  # 保存 bash 命令默认执行目录。

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        command = str(input_data.get("command", "")).strip()
        if not command:
            raise ValueError("bash command cannot be empty")
        cwd = context.workspace_path if context.workspace_path else self.cwd
        if not cwd.exists():
            cwd.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()
        completed = subprocess.run(
            ["bash", "-lc", command],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.config.command_timeout_seconds,
        )
        duration = time.monotonic() - started
        stdout_tail = completed.stdout[-self.config.stdout_tail_chars :]
        stderr_tail = completed.stderr[-self.config.stderr_tail_chars :]
        summary = f"exit_code={completed.returncode}, duration={duration:.2f}s"

        return ToolResult(
            success=completed.returncode == 0,
            summary=summary,
            data={
                "command": command,
                "exit_code": completed.returncode,
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
                "duration_seconds": duration,
            },
        )


def _build_bash_tool(context: ToolContext) -> BashTool:
    return BashTool(config=context.config, cwd=context.workspace_path)


register_tool_factory(BashTool.name, _build_bash_tool)
