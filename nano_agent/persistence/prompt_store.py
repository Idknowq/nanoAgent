from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from nano_agent.persistence.json_io import atomic_write_json
from nano_agent.prompts.assembler import PromptBundle


class PromptSnapshot(BaseModel):
    schema_version: int = 1  # Prompt 快照的数据结构版本。
    run_id: str  # Prompt 快照所属的 Agent 运行标识。
    created_at: datetime  # Prompt 快照的写入时间。
    prompt_version: str  # 本次使用的 prompt 组装协议版本。
    included_sections: list[str]  # 初始 prompt 实际包含的区块。
    available_skill_names: list[str]  # 初始 catalog 暴露的 Skill 名称。
    memory_keys: list[str]  # 初始 prompt 注入的 memory 标识。
    core_sha256: str  # 稳定核心 prompt 的内容摘要。
    estimated_chars: int  # 初始 prompt 的字符数估算。


class PromptStore:
    """Persist prompt composition metadata without duplicating message content."""

    filename = "prompt.json"  # 每个 run 保存 prompt 元数据的文件名。

    def save(self, run_id: str, run_dir: Path, bundle: PromptBundle) -> Path:
        snapshot = PromptSnapshot(
            run_id=run_id,
            created_at=datetime.now(timezone.utc),
            prompt_version=bundle.prompt_version,
            included_sections=bundle.included_sections,
            available_skill_names=bundle.available_skill_names,
            memory_keys=bundle.memory_keys,
            core_sha256=bundle.core_sha256,
            estimated_chars=bundle.estimated_chars,
        )
        target = run_dir / self.filename
        atomic_write_json(target, snapshot.model_dump(mode="json"))
        return target

    async def save_async(self, run_id: str, run_dir: Path, bundle: PromptBundle) -> Path:
        """Persist prompt metadata without blocking the event loop."""

        return await asyncio.to_thread(self.save, run_id, run_dir, bundle)
