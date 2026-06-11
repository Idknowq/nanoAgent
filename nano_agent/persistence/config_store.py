from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from nano_agent.config import AgentConfig
from nano_agent.persistence.json_io import atomic_write_json


class ConfigSnapshot(BaseModel):
    schema_version: int = 1
    run_id: str
    created_at: datetime
    config: dict


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
