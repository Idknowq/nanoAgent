from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    """Agent 运行整体状态。"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


TerminalRunStatus: TypeAlias = Literal[
    RunStatus.COMPLETED,
    RunStatus.BLOCKED,
    RunStatus.FAILED,
]


class ApprovalLevel(StrEnum):
    """工具调用所需的权限等级。"""

    READ = "read"
    EXECUTE_SAFE = "execute_safe"
    EXECUTE_RISKY = "execute_risky"
    WRITE = "write"
    NETWORK = "network"
    PUBLISH = "publish"


class LLMStopReason(StrEnum):
    """Provider-independent reason why one LLM response stopped."""

    TOOL_USE = "tool_use"
    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    CONTENT_FILTER = "content_filter"
    UNKNOWN = "unknown"


class ToolCallRecord(BaseModel):
    """一次工具调用的结构化记录，用于审计和上下文压缩。"""

    tool_call_id: str  # LLM 为本次工具调用生成的唯一标识。
    tool_name: str  # 被调用的工具名称，例如 run_command、read_file。
    input_summary: str  # 工具输入摘要，避免保存过大的原始输入。
    output_summary: str  # 工具输出摘要，用于复盘 Agent 判断依据。
    approval_level: ApprovalLevel  # 本次工具调用对应的权限等级。
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # 调用开始时间。
    duration_seconds: float | None = None  # 工具调用耗时；未统计时为空。
    success: bool  # 工具调用是否成功完成。


class ToolUseRequest(BaseModel):
    """LLM 请求 Agent 调用的一个工具。"""

    id: str  # 本次工具调用的唯一 id。
    name: str  # 被调用的工具名称。
    input: dict[str, Any] = Field(default_factory=dict)  # 工具输入参数。


class AgentMessage(BaseModel):
    """Agent 循环中的一条消息。"""

    role: Literal["system", "user", "assistant", "tool"]  # 消息角色。
    content: str  # 消息文本内容。
    tool_call_id: str | None = None  # tool 结果对应的工具调用 id。
    tool_uses: list[ToolUseRequest] = Field(default_factory=list)  # assistant 消息中的工具调用。


class LLMUsage(BaseModel):
    """一次 LLM 调用返回的 token 使用统计。"""

    input_tokens: int | None = None  # 请求消耗的输入 token 数。
    output_tokens: int | None = None  # 响应生成的输出 token 数。
    total_tokens: int | None = None  # 本次调用消耗的 token 总数。
    cached_tokens: int | None = None  # 输入 token 中命中缓存的数量。


class LLMResponse(BaseModel):
    """LLM 单轮响应，可能包含文本、工具调用或终止信号。"""

    content: str = ""  # LLM 返回的文本内容。
    tool_uses: list[ToolUseRequest] = Field(default_factory=list)  # LLM 请求调用的工具列表。
    stop_reason: LLMStopReason = LLMStopReason.END_TURN  # 规范化后的本轮停止原因。
    provider_stop_reason: str | None = None  # Provider 返回的原始停止原因。
    truncated_tool_call: bool = False  # 截断响应是否包含无法完整解析的工具调用。
    provider: str | None = None  # 实际响应对应的 provider。
    model: str | None = None  # 实际响应对应的模型名。
    usage: LLMUsage | None = None  # provider 返回的 token 使用量。


class CompletionReport(BaseModel):
    """User-facing completion data used to render report.md."""

    status: TerminalRunStatus  # 最终状态：完成、阻塞或失败。
    problem: str  # 发现的问题或任务目标概述。
    root_cause: str  # 问题根因；无法确定时说明当前判断。
    resolution: str  # 已实施的修复或采取的处理方式。
    changed_files: list[str] = Field(default_factory=list)  # 实际修改的仓库相对路径。
    verification_summary: str = ""  # 验证命令、范围和结果摘要。
    remaining_risks: list[str] = Field(default_factory=list)  # 尚未消除的风险。
    blockers: list[str] = Field(default_factory=list)  # 阻塞任务继续完成的原因。


class RunSummary(BaseModel):
    """一次 Agent 运行的最终摘要和中间产物索引。"""

    run_id: str  # 本次运行的唯一标识，目前使用 UTC 时间戳生成。
    repo_url: str  # 用户输入的目标仓库地址。
    workspace_path: Path | None = None  # 目标仓库 clone 后所在的隔离工作区路径。
    status: RunStatus = RunStatus.PENDING  # 本次 Agent 运行的整体状态。
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )  # 本次运行的开始时间。
    finished_at: datetime | None = None  # 本次运行的结束时间；运行中为空。
    steps: int = 0  # Agent loop 实际执行的步骤数。
    llm_call_count: int = 0  # 本次运行发起的 LLM 调用次数。
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)  # 工具调用审计记录。
    messages: list[AgentMessage] = Field(default_factory=list)  # Agent 循环中的消息历史。
    completion_report: CompletionReport | None = None  # 通过终止协议确认的最终报告。
    notes: list[str] = Field(default_factory=list)  # 面向用户或开发者的补充说明。
    artifacts: dict[str, Any] = Field(default_factory=dict)  # 结构化中间产物。
