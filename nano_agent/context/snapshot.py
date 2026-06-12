from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from nano_agent.models import AgentMessage


class ContextEvent(BaseModel):
    tool_call_id: str  # 事件对应的工具调用 id，用于避免重复注入。
    tool_name: str  # 产生该上下文事件的工具名称。
    summary: str  # 工具失败结果的截断摘要。


class RunContextSnapshot(BaseModel):
    """Bounded durable state derived from the append-only conversation."""

    repo_url: str  # 当前运行处理的目标仓库地址。
    workspace_state: Literal["not_cloned", "ready"] = "not_cloned"  # 仓库 clone 状态。
    current_step: int = 0  # 当前 Agent loop 步骤，仅用于初始上下文展示。
    max_steps: int = 0  # 当前 Agent loop 最大步骤数。
    inspected_files: list[str] = Field(default_factory=list)  # 已成功读取的文件路径。
    modified_files: list[str] = Field(default_factory=list)  # 已成功修改的文件路径。
    successful_commands: list[str] = Field(default_factory=list)  # 已成功执行的命令摘要。
    failures: list[ContextEvent] = Field(default_factory=list)  # 尚可用于后续判断的失败事件。

    def to_prompt(self) -> str:
        lines = [
            "<runtime_context>",
            f"<repository>{escape(self.repo_url)}</repository>",
            f"<workspace_state>{self.workspace_state}</workspace_state>",
            f"<step>{self.current_step}/{self.max_steps}</step>",
        ]
        lines.extend(self._list_section("inspected_files", self.inspected_files))
        lines.extend(self._list_section("modified_files", self.modified_files))
        lines.extend(self._list_section("successful_commands", self.successful_commands))
        lines.append("</runtime_context>")
        return "\n".join(lines)

    @staticmethod
    def _list_section(name: str, values: list[str]) -> list[str]:
        if not values:
            return []
        return [f"<{name}>", *(f"- {escape(value)}" for value in values), f"</{name}>"]


class RunContextBuilder:
    """Build bounded durable snapshots from protocol messages."""

    def __init__(self, max_items: int = 20, max_failures: int = 20) -> None:
        self.max_items = max_items  # 每类累计事实最多保留的数量。
        self.max_failures = max_failures  # 快照最多保留的失败事件数量。

    def build(
        self,
        *,
        repo_url: str,
        workspace_path: Path,
        current_step: int,
        max_steps: int,
        messages: list[AgentMessage],
    ) -> RunContextSnapshot:
        calls = self._tool_calls(messages)
        inspected: list[str] = []
        modified: list[str] = []
        successful_commands: list[str] = []
        failures: list[ContextEvent] = []

        for message in messages:
            if message.role != "tool" or not message.tool_call_id:
                continue
            call = calls.get(message.tool_call_id)
            if call is None:
                continue
            try:
                result = json.loads(message.content)
            except json.JSONDecodeError:
                continue
            tool_name, tool_input = call
            success = bool(result.get("success"))
            summary = str(result.get("summary", ""))[:500]
            if not success and tool_name != "activate_skill":
                failures.append(
                    ContextEvent(
                        tool_call_id=message.tool_call_id,
                        tool_name=tool_name,
                        summary=summary,
                    )
                )
            if tool_name == "read_file" and success:
                self._append_unique(inspected, str(tool_input.get("path", "")))
            elif tool_name == "edit_file" and success:
                self._append_unique(modified, str(tool_input.get("path", "")))
            elif tool_name == "run_command" and success:
                program = str(tool_input.get("program", ""))
                args = " ".join(str(value) for value in tool_input.get("args", []))
                self._append_unique(successful_commands, f"{program} {args}".strip())

        return RunContextSnapshot(
            repo_url=repo_url,
            workspace_state="ready" if (workspace_path / ".git").exists() else "not_cloned",
            current_step=current_step,
            max_steps=max_steps,
            inspected_files=inspected[-self.max_items :],
            modified_files=modified[-self.max_items :],
            successful_commands=successful_commands[-self.max_items :],
            failures=failures[-self.max_failures :],
        )

    @staticmethod
    def _tool_calls(messages: list[AgentMessage]) -> dict[str, tuple[str, dict[str, Any]]]:
        calls: dict[str, tuple[str, dict[str, Any]]] = {}
        for message in messages:
            for tool_use in message.tool_uses:
                calls[tool_use.id] = (tool_use.name, tool_use.input)
        return calls

    @staticmethod
    def _append_unique(target: list[str], value: str) -> None:
        if value and value not in target:
            target.append(value)
