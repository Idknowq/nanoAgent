from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.models import RunSummary
from nano_agent.persistence.summary_store import SummaryStore


class WorkspaceManager:
    """创建隔离工作区，并持久化每次运行的摘要。"""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config  # 保存工作区路径、run summary 路径等运行配置。
        self.summary_store = SummaryStore()

    def create_run(self, repo_url: str) -> RunSummary:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return RunSummary(run_id=run_id, repo_url=repo_url)

    def next_workspace_path(self, repo_url: str, run_id: str) -> Path:
        self.config.workspace_root.mkdir(parents=True, exist_ok=True)
        repo_name = self._repo_name_from_url(repo_url)
        return self.config.workspace_root / f"{repo_name}-{run_id}"

    def run_dir(self, run_id: str) -> Path:
        """Return the directory that owns all persisted artifacts for one run."""
        return self.config.runs_root / run_id

    def save_run_summary(self, run: RunSummary) -> Path:
        return self.summary_store.save(self.run_dir(run.run_id), run)

    async def save_run_summary_async(self, run: RunSummary) -> Path:
        """Persist the run summary without blocking the event loop."""

        return await self.summary_store.save_async(self.run_dir(run.run_id), run)

    def _repo_name_from_url(self, repo_url: str) -> str:
        raw_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_name).strip("-")
        return safe_name or "repo"
