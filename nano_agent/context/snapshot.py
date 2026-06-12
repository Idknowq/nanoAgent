from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from nano_agent.models import AgentMessage


class ContextEvent(BaseModel):
    tool_name: str  # 产生该上下文事件的工具名称。
    summary: str  # 工具结果的截断摘要。
    success: bool  # 本次工具调用是否成功。


class RunContextSnapshot(BaseModel):
    """Bounded, structured state supplied to the model instead of replay summaries."""

    repo_url: str  # 当前运行处理的目标仓库地址。
    workspace_state: Literal["not_cloned", "ready"] = "not_cloned"  # 仓库 clone 状态。
    current_step: int = 0  # 当前 Agent loop 步骤。
    max_steps: int = 0  # 当前 Agent loop 最大步骤数。
    inspected_files: list[str] = Field(default_factory=list)  # 已成功读取的文件路径。
    modified_files: list[str] = Field(default_factory=list)  # 已成功修改的文件路径。
    commands: list[str] = Field(default_factory=list)  # 已请求执行的命令摘要。
    recent_events: list[ContextEvent] = Field(default_factory=list)  # 最近工具事件。

    def to_prompt(self) -> str:
        lines = [
            "<runtime_context>",
            f"<repository>{self.repo_url}</repository>",
            f"<workspace_state>{self.workspace_state}</workspace_state>",
            f"<step>{self.current_step}/{self.max_steps}</step>",
        ]
        lines.extend(self._list_section("inspected_files", self.inspected_files))
        lines.extend(self._list_section("modified_files", self.modified_files))
        lines.extend(self._list_section("commands", self.commands))
        if self.recent_events:
            lines.append("<recent_events>")
            for event in self.recent_events:
                status = "success" if event.success else "failure"
                lines.append(
                    f'<event tool="{event.tool_name}" status="{status}">{event.summary}</event>'
                )
            lines.append("</recent_events>")
        lines.append("</runtime_context>")
        return "\n".join(lines)

    @staticmethod
    def _list_section(name: str, values: list[str]) -> list[str]:
        if not values:
            return []
        return [f"<{name}>", *(f"- {value}" for value in values), f"</{name}>"]


class RunContextBuilder:
    """Derive a compact snapshot from the append-only conversation protocol."""

    def __init__(self, max_items: int = 20, max_events: int = 6) -> None:
        self.max_items = max_items  # 每类累计事实最多保留的数量。
        self.max_events = max_events  # 最近工具事件最多保留的数量。

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
        commands: list[str] = []
        events: list[ContextEvent] = []

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
            events.append(ContextEvent(tool_name=tool_name, summary=summary, success=success))
            if tool_name == "read_file" and success:
                self._append_unique(inspected, str(tool_input.get("path", "")))
            elif tool_name == "edit_file" and success:
                self._append_unique(modified, str(tool_input.get("path", "")))
            elif tool_name == "run_command":
                program = str(tool_input.get("program", ""))
                args = " ".join(str(value) for value in tool_input.get("args", []))
                self._append_unique(commands, f"{program} {args}".strip())

        return RunContextSnapshot(
            repo_url=repo_url,
            workspace_state="ready" if (workspace_path / ".git").exists() else "not_cloned",
            current_step=current_step,
            max_steps=max_steps,
            inspected_files=inspected[-self.max_items :],
            modified_files=modified[-self.max_items :],
            commands=commands[-self.max_items :],
            recent_events=events[-self.max_events :],
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
