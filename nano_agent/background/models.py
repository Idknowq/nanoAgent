from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field

from nano_agent.subagents.models import SubagentResult


class BackgroundJobStatus(StrEnum):
    QUEUED = "queued"  # Job 已提交，等待 Supervisor 分配执行线程。
    RUNNING = "running"  # Job 对应的子 Agent 正在执行。
    SUCCEEDED = "succeeded"  # Job 已成功完成。
    BLOCKED = "blocked"  # Job 因外部条件阻塞。
    FAILED = "failed"  # Job 因执行错误或预算耗尽失败。
    CANCEL_REQUESTED = "cancel_requested"  # 运行中的 Job 已收到合作式取消请求。
    CANCELLED = "cancelled"  # Job 已在执行前或安全边界停止。


TERMINAL_JOB_STATUSES = {
    BackgroundJobStatus.SUCCEEDED,
    BackgroundJobStatus.BLOCKED,
    BackgroundJobStatus.FAILED,
    BackgroundJobStatus.CANCELLED,
}


class BackgroundJob(BaseModel):
    """One concrete background execution attempt for an isolated subagent."""

    schema_version: int = 1  # Job 快照的数据结构版本。
    job_id: str  # 当前后台执行的稳定标识。
    subagent_id: str  # 当前 Job 对应的子 Agent 标识。
    task_id: str | None = None  # 可选的持久化 Task 关联。
    status: BackgroundJobStatus = BackgroundJobStatus.QUEUED  # 当前 Job 生命周期状态。
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # Job 创建时间。
    started_at: datetime | None = None  # Job 实际开始执行的时间。
    finished_at: datetime | None = None  # Job 进入终态的时间。
    result: SubagentResult | None = None  # 子 Agent 的最终结构化结果。
    error: str | None = None  # Supervisor 层面的失败或取消摘要。


class BackgroundJobEvent(BaseModel):
    """One persisted lifecycle transition for a background job."""

    schema_version: int = 1  # Job 事件的数据结构版本。
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # Job 事件写入时间。
    job_id: str  # 事件对应的 Job 标识。
    status: BackgroundJobStatus  # 事件记录的最新状态。


class BackgroundCompletionEvent(BaseModel):
    """Terminal notification delivered to the parent agent."""

    job_id: str  # 已结束的 Job 标识。
    subagent_id: str  # 已结束的子 Agent 标识。
    task_id: str | None = None  # 可选的持久化 Task 标识。
    status: BackgroundJobStatus  # Job 最终状态。
