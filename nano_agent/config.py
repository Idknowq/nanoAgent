from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """单次 nanoAgent 进程的运行配置。"""

    workspace_root: Path = Field(default=Path(".nano/workspaces"))  # 目标仓库隔离 clone 目录。
    runs_root: Path = Field(default=Path(".nano/runs"))  # 每次运行摘要 JSON 的保存目录。
    llm_provider: str = "deepseek"  # 生产运行默认使用 DeepSeek。
    llm_model: str | None = None  # LLM 模型名；为空时由 provider 默认值决定。
    max_steps: int = Field(default=50, ge=1)  # Agent 最大执行步数，防止后续 planner 死循环。
    command_timeout_seconds: int = Field(default=120, ge=1)  # 单个 shell 命令的超时时间。
    execution_isolation_enabled: bool = True  # 是否启用 run 级命令执行环境隔离。
    python_executable: Path | None = None  # 创建隔离 Python 环境时使用的解释器。
    auto_approve: bool = False  # 是否自动批准高风险命令执行。
    auto_approve_write: bool = False  # 是否自动批准工作区文件修改。
    max_consecutive_tool_calls: int = Field(default=3, ge=1)  # 同一工具连续调用提醒阈值。
    llm_calls_enabled: bool = True  # 是否将 LLM 调用元数据写入 llm_calls.jsonl。
    audit_enabled: bool = True  # 是否将工具调用写入当前 run 的 audit.jsonl。
    audit_max_input_chars: int = Field(default=4_000, ge=100)  # 审计输入摘要最大长度。
    console_progress_enabled: bool = True  # 是否在终端显示 Agent 执行进度。
    max_file_bytes: int = Field(default=128_000, ge=1)  # 单个文件最多读取的字节数。
    stdout_tail_chars: int = Field(default=16_000, ge=1)  # stdout 最多保留的尾部字符数。
    stderr_tail_chars: int = Field(default=16_000, ge=1)  # stderr 最多保留的尾部字符数。
    skills_root: Path | None = None  # 可选的 Markdown skill 目录；为空时使用内置 skills。
    memory_path: Path | None = None  # 可选的跨运行 JSONL memory 文件。
    memory_limit: int = Field(default=5, ge=0, le=20)  # 初始 prompt 最多注入的 memory 数量。
    context_compaction_enabled: bool = True  # 是否启用 LLM 调用前上下文压缩管线。
    tool_result_budget_chars: int = Field(default=200_000, ge=1)  # 单轮工具结果字符预算。
    tool_result_preview_chars: int = Field(default=2_000, ge=0)  # 大结果落盘后的预览长度。
    snip_message_threshold: int = Field(default=50, ge=3)  # 触发中间消息裁剪的数量。
    snip_keep_head: int = Field(default=5, ge=1)  # snip 时保留的头部消息数。
    snip_keep_tail: int = Field(default=20, ge=1)  # snip 时保留的尾部消息数。
    micro_keep_recent_tool_results: int = Field(default=6, ge=0)  # 保留完整的最近工具结果数。
    micro_tool_result_min_chars: int = Field(default=2_000, ge=1)  # micro 压缩最小长度。
    context_max_input_tokens: int = Field(default=60_000, ge=1_000)  # Agent 输入 token 预算。
    context_auto_compact_ratio: float = Field(default=0.8, gt=0, le=1)  # 自动摘要阈值比例。
    context_output_reserve_tokens: int = Field(default=8_000, ge=0)  # 为模型输出保留的 token。
    max_auto_compactions: int = Field(default=3, ge=0, le=3)  # 单次 run 自动摘要上限。
    reactive_keep_recent_messages: int = Field(default=8, ge=1)  # 应急压缩保留的尾部消息数。
    max_reactive_compactions: int = Field(default=1, ge=0, le=1)  # 单次 run 应急压缩上限。
