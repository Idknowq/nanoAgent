from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field

from nano_agent.models import CompletionReport


class SubagentStatus(StrEnum):
    CREATED = "created"  # 子 Agent 已创建但尚未开始执行。
    RUNNING = "running"  # 子 Agent 正在执行任务。
    SUCCEEDED = "succeeded"  # 子 Agent 已成功完成任务。
    BLOCKED = "blocked"  # 子 Agent 因外部条件阻塞。
    FAILED = "failed"  # 子 Agent 因错误或额度限制失败。
    CANCELLED = "cancelled"  # 子 Agent 已被外部取消。


class SubagentErrorKind(StrEnum):
    BLOCKED = "blocked"  # 子 Agent 因外部条件阻塞。
    STEP_LIMIT = "step_limit"  # 子 Agent 超过循环步骤上限。
    LLM_CALL_LIMIT = "llm_call_limit"  # 子 Agent 超过 LLM 调用预算。
    INVALID_REQUEST = "invalid_request"  # 委派请求参数或权限无效。
    EXECUTION_ERROR = "execution_error"  # 子 Agent 发生未分类执行错误。


class SubagentRequest(BaseModel):
    task: str = Field(min_length=1)  # 主 Agent 委派给子 Agent 的任务描述。
    context: str | None = None  # 主 Agent 显式提供的背景信息。
    allowed_tools: tuple[str, ...] = ()  # 子 Agent 可使用的业务工具名称。
    max_steps: int = Field(ge=1)  # 子 Agent 的最大循环步骤数。
    max_llm_calls: int = Field(ge=1)  # 子 Agent 的物理 LLM 调用预算。


class SubagentResult(BaseModel):
    subagent_id: str  # 当前子 Agent 的唯一标识。
    parent_run_id: str  # 创建当前子 Agent 的父运行标识。
    status: SubagentStatus  # 子 Agent 的最终生命周期状态。
    output: str | None = None  # 成功时回传给主 Agent 的受限文本结果。
    error_kind: SubagentErrorKind | None = None  # 失败时的稳定错误分类。
    error: str | None = None  # 失败时回传给主 Agent 的错误摘要。
    steps_used: int = 0  # 子 Agent 实际使用的循环步骤数。
    llm_calls_used: int = 0  # 子 Agent 实际发起的物理 LLM 调用数。
    completion_report: CompletionReport | None = None  # 子 Agent 提交的完整终止报告。
    run_dir: str  # 子 Agent 持久化目录路径。
    result_path: str = "result.json"  # 完整结构化结果相对子运行目录的路径。
    summary_path: str = "summary.json"  # 子运行摘要相对子运行目录的路径。
    messages_path: str = "messages.jsonl"  # 子消息轨迹相对子运行目录的路径。


class SubagentState(BaseModel):
    schema_version: int = 1  # 子 Agent 状态文件结构版本。
    subagent_id: str  # 当前子 Agent 的唯一标识。
    parent_run_id: str  # 创建当前子 Agent 的父运行标识。
    status: SubagentStatus  # 当前生命周期状态。
    task: str  # 当前子 Agent 接收的任务描述。
    allowed_tools: tuple[str, ...]  # 当前子 Agent 获得的业务工具名称。
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # 子 Agent 创建时间。
    started_at: datetime | None = None  # 子 Agent 开始执行时间。
    finished_at: datetime | None = None  # 子 Agent 进入终态的时间。
    result: SubagentResult | None = None  # 子 Agent 的结构化最终结果。

    def transition(self, target: SubagentStatus) -> None:
        allowed = {
            SubagentStatus.CREATED: {SubagentStatus.RUNNING, SubagentStatus.CANCELLED},
            SubagentStatus.RUNNING: {
                SubagentStatus.SUCCEEDED,
                SubagentStatus.BLOCKED,
                SubagentStatus.FAILED,
                SubagentStatus.CANCELLED,
            },
            SubagentStatus.SUCCEEDED: set(),
            SubagentStatus.BLOCKED: set(),
            SubagentStatus.FAILED: set(),
            SubagentStatus.CANCELLED: set(),
        }
        if target not in allowed[self.status]:
            raise ValueError(
                f"Invalid subagent state transition: {self.status.value} -> {target.value}"
            )
        self.status = target


class SubagentLifecycleEvent(BaseModel):
    schema_version: int = 1  # 生命周期事件结构版本。
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # 生命周期状态写入时间。
    subagent_id: str  # 事件对应的子 Agent 标识。
    parent_run_id: str  # 事件对应的父运行标识。
    status: SubagentStatus  # 本次事件记录的生命周期状态。
