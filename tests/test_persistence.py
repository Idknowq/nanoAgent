import json
from pathlib import Path

from nano_agent.agent import NanoAgent
from nano_agent.config import AgentConfig
from nano_agent.models import AgentMessage, LLMResponse, ToolUseRequest
from nano_agent.persistence.config_store import ConfigStore
from nano_agent.persistence.message_store import MessageStore


class TodoThenFinishLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="track work",
                stop_reason="tool_use",
                provider="test",
                model="test-model",
                tool_uses=[
                    ToolUseRequest(
                        id="tool-1",
                        name="todo_write",
                        input={"action": "add", "title": "Inspect repository"},
                    )
                ],
            )
        return LLMResponse(
            content="done",
            stop_reason="end_turn",
            provider="test",
            model="test-model",
        )


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
            tool_uses=[ToolUseRequest(id="tool-1", name="read_file", input={"path": "README.md"})],
        ),
    ]

    store.append(messages[0])
    store.append(messages[1], llm_call_id="llm-1")

    records = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
    assert [record["sequence"] for record in records] == [1, 2]
    assert records[1]["llm_call_id"] == "llm-1"
    assert records[1]["message"]["tool_uses"][0]["input"] == {"path": "README.md"}
    assert MessageStore(tmp_path / "run-1").load_messages() == messages


def test_nano_agent_persists_run_files_including_prompt_metadata(tmp_path: Path) -> None:
    config = AgentConfig(
        workspace_root=tmp_path / "workspaces",
        runs_root=tmp_path / "runs",
        console_progress_enabled=False,
    )

    result = NanoAgent(config, llm=TodoThenFinishLLM()).run(  # type: ignore[arg-type]
        "https://example.com/repo.git"
    )

    run_dir = config.runs_root / result.run_id
    assert result.status == "succeeded"
    assert {path.name for path in run_dir.iterdir()} == {
        "audit.jsonl",
        "config.json",
        "context_checkpoint.json",
        "llm_calls.jsonl",
        "messages.jsonl",
        "prompt.json",
        "summary.json",
    }
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    audit = json.loads((run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    llm_call = json.loads(
        (run_dir / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert summary["llm_call_count"] == 2
    assert summary["tool_call_count"] == 1
    assert "messages" not in summary
    assert audit["llm_call_id"] == llm_call["llm_call_id"] == "llm-1"
    prompt = json.loads((run_dir / "prompt.json").read_text(encoding="utf-8"))
    assert prompt["prompt_version"] == "mvp-v1"
    assert prompt["included_sections"] == ["core", "skill_catalog", "context", "task"]
    assert prompt["available_skill_names"] == [
        "github-actions",
        "node-repository",
        "python-repository",
    ]
