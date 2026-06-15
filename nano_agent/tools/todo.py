from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import (
    RuntimeTool,
    ToolContext,
    ToolInput,
    ToolResult,
    register_tool_factory,
)
from nano_agent.tools.errors import ToolInputError


class TodoWriteInput(ToolInput):
    action: Literal["add", "start", "complete", "fail", "skip"]
    title: str = ""
    id: str | None = None
    evidence: str | None = Field(default=None)


class TodoStatus(StrEnum):
    """todo_write 工具内部 todo 项的执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TodoItem(BaseModel):
    """todo_write 工具内部的一条短期 todo。"""

    id: str  # todo 的工具内部稳定标识。
    title: str  # 给 LLM 和审计结果展示的简短任务名称。
    status: TodoStatus = TodoStatus.PENDING  # 该 todo 的当前执行状态。
    evidence: str | None = None  # 完成、失败或调整时留下的证据。


class TodoList:
    """todo_write 工具的内部短期状态存储。

    它只服务于 TodoWriteTool，不代表未来 planner、调度器或任务状态机。
    """

    def __init__(self) -> None:
        self._items: list[TodoItem] = []  # 保存当前工具实例维护的 todo 项。
        self._next_id = 1  # 生成当前工具实例内递增 todo id。

    @property
    def items(self) -> list[TodoItem]:
        return list(self._items)

    def add(self, title: str, evidence: str | None = None) -> TodoItem:
        item = TodoItem(id=self._new_id(), title=title, evidence=evidence)
        self._items.append(item)
        return item

    def start(self, item_id: str, evidence: str | None = None) -> None:
        item = self._find(item_id)
        item.status = TodoStatus.RUNNING
        item.evidence = evidence

    def complete(self, item_id: str, evidence: str | None = None) -> None:
        item = self._find(item_id)
        item.status = TodoStatus.COMPLETED
        item.evidence = evidence

    def fail(self, item_id: str, evidence: str | None = None) -> None:
        item = self._find(item_id)
        item.status = TodoStatus.FAILED
        item.evidence = evidence

    def skip(self, item_id: str, evidence: str | None = None) -> None:
        item = self._find(item_id)
        item.status = TodoStatus.SKIPPED
        item.evidence = evidence

    def _new_id(self) -> str:
        item_id = f"todo-{self._next_id}"
        self._next_id += 1
        return item_id

    def _find(self, item_id: str) -> TodoItem:
        for item in self._items:
            if item.id == item_id:
                return item
        raise KeyError(f"Todo item not found: {item_id}")


class TodoWriteTool(RuntimeTool):
    """可选 todo 工具，用于 LLM 维护会话内短期任务。"""

    name = "todo_write"
    description = (
        "Create or update an optional short-lived checklist for genuinely multi-step work. "
        "Do not use for an obvious one-step action."
    )
    approval_level = ApprovalLevel.READ
    category = "planning"
    input_model = TodoWriteInput
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "start", "complete", "fail", "skip"],
                "description": "Todo operation to perform.",
            },
            "title": {"type": "string", "description": "Todo title, required for add."},
            "id": {"type": "string", "description": "Todo id, required for update actions."},
            "evidence": {"type": "string", "description": "Short evidence or status note."},
        },
        "required": ["action"],
    }

    def __init__(self) -> None:
        self.todos = TodoList()  # 保存 todo_write 工具的内部短期状态。

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        action = str(input_data.get("action", "add"))
        title = str(input_data.get("title", "")).strip()
        item_id = input_data.get("id")
        evidence = input_data.get("evidence")

        if action == "add":
            if not title:
                raise ToolInputError("todo title is required for add")
            item = self.todos.add(title=title, evidence=evidence)
            return ToolResult(success=True, summary=f"added {item.id}", data={"todos": self._dump()})

        if not item_id:
            raise ToolInputError("todo id is required for update actions")
        try:
            if action == "start":
                self.todos.start(str(item_id), evidence=evidence)
            elif action == "complete":
                self.todos.complete(str(item_id), evidence=evidence)
            elif action == "fail":
                self.todos.fail(str(item_id), evidence=evidence)
            elif action == "skip":
                self.todos.skip(str(item_id), evidence=evidence)
            else:
                raise ToolInputError(f"unknown todo action: {action}")
        except KeyError as exc:
            raise ToolInputError(str(exc)) from exc

        return ToolResult(success=True, summary=f"{action} {item_id}", data={"todos": self._dump()})

    def _dump(self) -> list[dict]:
        return [item.model_dump(mode="json") for item in self.todos.items]


def _build_todo_write_tool(context: ToolContext) -> TodoWriteTool:
    return TodoWriteTool()


register_tool_factory(TodoWriteTool.name, _build_todo_write_tool)
