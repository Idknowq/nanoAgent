from __future__ import annotations

from pydantic import Field

from nano_agent.models import ApprovalLevel
from nano_agent.tasks.models import TaskStatus
from nano_agent.tasks.service import TaskService
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolInput, ToolResult


class TaskCreateInput(ToolInput):
    subject: str = Field(min_length=1, max_length=200)  # Task 的简短标题。
    description: str = Field(min_length=1, max_length=8_000)  # Task 的完整工作说明。
    blocked_by: tuple[str, ...] = ()  # 当前 Task 依赖的前置 Task 标识。


class TaskGetInput(ToolInput):
    task_id: str = Field(pattern=r"^task-\d+$")  # 需要查询的 Task 标识。


class TaskListInput(ToolInput):
    status: TaskStatus | None = None  # 可选的 Task 状态过滤条件。


class TaskUpdateInput(ToolInput):
    task_id: str = Field(pattern=r"^task-\d+$")  # 需要更新的 Task 标识。
    subject: str | None = Field(default=None, min_length=1, max_length=200)  # 新 Task 标题。
    description: str | None = Field(
        default=None,
        min_length=1,
        max_length=8_000,
    )  # 新 Task 工作说明。
    status: TaskStatus | None = None  # 需要转换到的 Task 状态。
    blocked_by: tuple[str, ...] | None = None  # 替换后的前置依赖集合。
    owner: str | None = Field(default=None, min_length=1, max_length=200)  # 新执行者标识。
    result: str | None = Field(default=None, max_length=8_000)  # Task 完成结果摘要。
    error: str | None = Field(default=None, max_length=8_000)  # Task 错误或阻塞摘要。


class TaskCreateTool(RuntimeTool):
    """Create one persistent task with optional dependencies."""

    name = "task_create"  # 工具注册名称。
    description = (
        "Create one durable work record only when persistent tracking, independent ownership, "
        "or a real dependency is useful. Set blocked_by for prerequisites. Normal investigation "
        "and trivial changes do not require a Task."
    )  # 工具说明。
    approval_level = ApprovalLevel.READ  # Task 元数据写入不修改目标工作区。
    category = "task"  # 工具所属功能分类。
    input_model = TaskCreateInput  # 工具输入校验模型。
    input_schema = TaskCreateInput.model_json_schema()  # 暴露给 LLM 的输入结构。

    def __init__(self, service: TaskService) -> None:
        self.service = service  # 当前主运行绑定的 Task 业务服务。

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        del context
        task = self.service.create(
            subject=input_data["subject"],
            description=input_data["description"],
            blocked_by=input_data["blocked_by"],
        )
        return ToolResult(
            success=True,
            summary=f"created {task.task_id} with status {task.status.value}",
            data={"task": task.model_dump(mode="json")},
        )


class TaskGetTool(RuntimeTool):
    """Get the complete current record for one task."""

    name = "task_get"  # 工具注册名称。
    description = (
        "Get the full current record for one known task_id before executing or updating it."
    )  # 工具说明。
    approval_level = ApprovalLevel.READ  # 查询 Task 不修改目标工作区。
    category = "task"  # 工具所属功能分类。
    input_model = TaskGetInput  # 工具输入校验模型。
    input_schema = TaskGetInput.model_json_schema()  # 暴露给 LLM 的输入结构。

    def __init__(self, service: TaskService) -> None:
        self.service = service  # 当前主运行绑定的 Task 业务服务。

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        del context
        task = self.service.get(input_data["task_id"])
        return ToolResult(
            success=True,
            summary=f"loaded {task.task_id} with status {task.status.value}",
            data={"task": task.model_dump(mode="json")},
        )


class TaskListTool(RuntimeTool):
    """List persistent tasks with an optional status filter."""

    name = "task_list"  # 工具注册名称。
    description = (
        "Review persistent work units and their current states, optionally filtered by status. "
        "Use to choose ready work or check dependency progress."
    )  # 工具说明。
    approval_level = ApprovalLevel.READ  # 查询 Task 不修改目标工作区。
    category = "task"  # 工具所属功能分类。
    input_model = TaskListInput  # 工具输入校验模型。
    input_schema = TaskListInput.model_json_schema()  # 暴露给 LLM 的输入结构。

    def __init__(self, service: TaskService) -> None:
        self.service = service  # 当前主运行绑定的 Task 业务服务。

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        del context
        tasks = self.service.list(input_data["status"])
        return ToolResult(
            success=True,
            summary=f"listed {len(tasks)} task(s)",
            data={"tasks": [task.model_dump(mode="json") for task in tasks]},
        )


class TaskUpdateTool(RuntimeTool):
    """Update task metadata, dependencies, or lifecycle status."""

    name = "task_update"  # 工具注册名称。
    description = (
        "Keep a persistent task accurate as work progresses. Mark it in_progress before work "
        "and completed, failed, blocked, or cancelled immediately after the outcome; include "
        "a concise result or error when applicable. Do not update execution fields for a Task "
        "linked to a background Job; the runtime manages those fields."
    )  # 工具说明。
    approval_level = ApprovalLevel.READ  # Task 元数据写入不修改目标工作区。
    category = "task"  # 工具所属功能分类。
    input_model = TaskUpdateInput  # 工具输入校验模型。
    input_schema = TaskUpdateInput.model_json_schema()  # 暴露给 LLM 的输入结构。

    def __init__(self, service: TaskService) -> None:
        self.service = service  # 当前主运行绑定的 Task 业务服务。

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        del context
        task_id = input_data.pop("task_id")
        task = self.service.update(task_id, **input_data)
        return ToolResult(
            success=True,
            summary=f"updated {task.task_id} to {task.status.value}",
            data={"task": task.model_dump(mode="json")},
        )
