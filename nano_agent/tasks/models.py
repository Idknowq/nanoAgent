from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"  # 任务依赖已满足，等待执行。
    IN_PROGRESS = "in_progress"  # 任务当前正在执行。
    BLOCKED = "blocked"  # 任务因依赖或外部条件阻塞。
    COMPLETED = "completed"  # 任务已成功完成。
    FAILED = "failed"  # 任务执行失败，可显式重试。
    CANCELLED = "cancelled"  # 任务已取消，不再执行。


class TaskBlockedReason(StrEnum):
    DEPENDENCY = "dependency"  # 任务存在尚未完成的前置依赖。
    EXTERNAL = "external"  # 任务因权限、输入或外部服务阻塞。


class TaskRecord(BaseModel):
    schema_version: int = 1  # Task 快照的数据结构版本。
    task_id: str  # 当前 Task 的稳定标识。
    subject: str  # 面向任务列表展示的简短标题。
    description: str  # Task 的完整工作说明。
    status: TaskStatus = TaskStatus.PENDING  # Task 当前状态。
    blocked_by: tuple[str, ...] = ()  # 当前 Task 依赖的前置 Task 标识。
    blocked_reason: TaskBlockedReason | None = None  # 当前阻塞状态的来源。
    owner: str | None = None  # 当前负责该 Task 的 Agent 或执行者标识。
    result: str | None = None  # Task 成功完成后的结果摘要。
    error: str | None = None  # Task 失败或阻塞时的错误摘要。
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # Task 创建时间。
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # Task 最近更新时间。


class TaskEvent(BaseModel):
    schema_version: int = 1  # Task 事件的数据结构版本。
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # Task 事件写入时间。
    task_id: str  # 事件对应的 Task 标识。
    event_type: str  # 事件类型，例如 created 或 updated。
    previous_status: TaskStatus | None = None  # 事件发生前的 Task 状态。
    current_status: TaskStatus  # 事件发生后的 Task 状态。
