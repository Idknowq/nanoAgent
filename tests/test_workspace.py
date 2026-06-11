import json
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.models import RunSummary
from nano_agent.workspace import WorkspaceManager


def test_save_run_summary_uses_per_run_directory(tmp_path: Path) -> None:
    config = AgentConfig(runs_root=tmp_path / "runs")
    manager = WorkspaceManager(config)
    run = RunSummary(run_id="run-1", repo_url="https://example.com/repo.git")

    target = manager.save_run_summary(run)

    assert target == config.runs_root / "run-1" / "summary.json"
    assert json.loads(target.read_text(encoding="utf-8"))["run_id"] == "run-1"


def test_run_dir_does_not_create_directory(tmp_path: Path) -> None:
    config = AgentConfig(runs_root=tmp_path / "runs")
    manager = WorkspaceManager(config)

    run_dir = manager.run_dir("run-1")

    assert run_dir == config.runs_root / "run-1"
    assert not run_dir.exists()
