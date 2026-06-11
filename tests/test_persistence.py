import json
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.persistence.config_store import ConfigStore


def test_config_store_writes_effective_config(tmp_path: Path) -> None:
    config = AgentConfig(
        workspace_root=tmp_path / "workspaces",
        runs_root=tmp_path / "runs",
        max_steps=7,
    )

    target = ConfigStore().save("run-1", tmp_path / "runs" / "run-1", config)

    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1
    assert persisted["run_id"] == "run-1"
    assert persisted["config"]["max_steps"] == 7
    assert persisted["config"]["workspace_root"] == str(tmp_path / "workspaces")
