from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.models import RunSummary


class WorkspaceManager:
    """创建隔离工作区，并持久化每次运行的摘要。"""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config  # 保存工作区路径、run summary 路径等运行配置。

    def create_run(self, repo_url: str) -> RunSummary:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return RunSummary(run_id=run_id, repo_url=repo_url)

    def next_workspace_path(self, repo_url: str, run_id: str) -> Path:
        self.config.workspace_root.mkdir(parents=True, exist_ok=True)
        repo_name = self._repo_name_from_url(repo_url)
        return self.config.workspace_root / f"{repo_name}-{run_id}"

    def save_run_summary(self, run: RunSummary) -> Path:
        self.config.runs_root.mkdir(parents=True, exist_ok=True)
        target = self.config.runs_root / f"{run.run_id}.json"
        target.write_text(
            json.dumps(run.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return target

    def _repo_name_from_url(self, repo_url: str) -> str:
        raw_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_name).strip("-")
        return safe_name or "repo"
