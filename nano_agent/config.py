from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """单次 nanoAgent 进程的运行配置。"""

    workspace_root: Path = Field(default=Path(".nano/workspaces"))  # 目标仓库隔离 clone 目录。
    runs_root: Path = Field(default=Path(".nano/runs"))  # 每次运行摘要 JSON 的保存目录。
    llm_provider: str = "deepseek"  # 生产运行默认使用 DeepSeek。
    llm_model: str | None = None  # LLM 模型名；为空时由 provider 默认值决定。
    max_steps: int = Field(default=20, ge=1)  # Agent 最大执行步数，防止后续 planner 死循环。
    command_timeout_seconds: int = Field(default=120, ge=1)  # 单个 shell 命令的超时时间。
    auto_approve: bool = False  # 是否自动批准高风险命令执行。
    max_file_bytes: int = Field(default=128_000, ge=1)  # 单个文件最多读取的字节数。
    stdout_tail_chars: int = Field(default=16_000, ge=1)  # stdout 最多保留的尾部字符数。
    stderr_tail_chars: int = Field(default=16_000, ge=1)  # stderr 最多保留的尾部字符数。
