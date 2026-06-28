from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from nano_agent.config import AgentConfig
from nano_agent.persistence.json_io import atomic_write_json


class ConfigSnapshot(BaseModel):
    schema_version: int = 1  # 配置快照的数据结构版本。
    run_id: str  # 配置所属的 Agent 运行标识。
    created_at: datetime  # 配置快照的写入时间。
    config: dict  # 本次运行实际生效的非敏感配置。


class ConfigStore:
    """Persist the effective non-secret configuration for one run."""

    filename = "config.json"

    def save(self, run_id: str, run_dir: Path, config: AgentConfig) -> Path:
        target = run_dir / self.filename
        snapshot = ConfigSnapshot(
            run_id=run_id,
            created_at=datetime.now(timezone.utc),
            config=config.model_dump(mode="json"),
        )
        atomic_write_json(target, snapshot.model_dump(mode="json"))
        return target

    async def save_async(self, run_id: str, run_dir: Path, config: AgentConfig) -> Path:
        """Persist the effective configuration without blocking the event loop."""

        return await asyncio.to_thread(self.save, run_id, run_dir, config)
