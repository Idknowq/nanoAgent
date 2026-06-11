import json
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.models import AgentMessage, ToolUseRequest
from nano_agent.persistence.config_store import ConfigStore
from nano_agent.persistence.message_store import MessageStore


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


def test_message_store_appends_and_recovers_complete_messages(tmp_path: Path) -> None:
    store = MessageStore(tmp_path / "run-1")
    messages = [
        AgentMessage(role="user", content="inspect repository"),
        AgentMessage(
            role="assistant",
            content="reading",
            tool_uses=[
                ToolUseRequest(id="tool-1", name="read_file", input={"path": "README.md"})
            ],
        ),
    ]

    store.append(messages[0])
    store.append(messages[1], llm_call_id="llm-1")

    records = [
        json.loads(line)
        for line in store.path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["sequence"] for record in records] == [1, 2]
    assert records[1]["llm_call_id"] == "llm-1"
    assert records[1]["message"]["tool_uses"][0]["input"] == {"path": "README.md"}
    assert MessageStore(tmp_path / "run-1").load_messages() == messages
