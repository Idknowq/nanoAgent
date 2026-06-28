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

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
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
            content="submit report",
            stop_reason="tool_use",
            provider="test",
            model="test-model",
            tool_uses=[
                ToolUseRequest(
                    id="finish-1",
                    name="finish_run",
                    input={
                        "status": "completed",
                        "problem": "Repository inspection was requested.",
                        "root_cause": "No defect was required for this persistence test.",
                        "resolution": "Recorded and verified the test todo.",
                        "verification_summary": "todo_write completed successfully.",
                    },
                )
            ],
        )


async def test_config_store_writes_effective_config(tmp_path: Path) -> None:
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


async def test_message_store_appends_and_recovers_complete_messages(tmp_path: Path) -> None:
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


async def test_nano_agent_persists_run_files_including_prompt_metadata(tmp_path: Path) -> None:
    config = AgentConfig(
        workspace_root=tmp_path / "workspaces",
        runs_root=tmp_path / "runs",
        console_progress_enabled=False,
    )

    result = await NanoAgent(config, llm=TodoThenFinishLLM()).run(  # type: ignore[arg-type]
        "https://example.com/repo.git",
        "Inspect package metadata and repair verified defects.",
    )

    run_dir = config.runs_root / result.run_id
    assert result.status == "completed"
    assert {path.name for path in run_dir.iterdir()} == {
        "audit.jsonl",
        "config.json",
        "context_checkpoint.json",
        "llm_calls.jsonl",
        "messages.jsonl",
        "prompt.json",
        "report.md",
        "summary.json",
    }
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    audit = json.loads((run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    llm_call = json.loads(
        (run_dir / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert summary["llm_call_count"] == 2
    assert summary["tool_call_count"] == 2
    assert summary["status"] == "completed"
    assert "outcome" not in summary
    assert "messages" not in summary
    assert audit["llm_call_id"] == llm_call["llm_call_id"] == "llm-1"
    prompt = json.loads((run_dir / "prompt.json").read_text(encoding="utf-8"))
    assert prompt["prompt_version"] == "mvp-v2"
    assert prompt["included_sections"] == ["core", "skill_catalog", "task"]
    assert prompt["available_skill_names"] == [
        "django-repository",
        "github-actions",
        "node-repository",
        "python-repository",
    ]
    messages = [
        json.loads(line)["message"]
        for line in (run_dir / "messages.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        "Inspect package metadata and repair verified defects." in message["content"]
        for message in messages
    )
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "# nanoAgent Run Report" in report
    assert "**Status:** completed" in report
    assert "Repository inspection was requested." in report


async def test_disabled_context_compaction_omits_checkpoint_artifact(tmp_path: Path) -> None:
    config = AgentConfig(
        workspace_root=tmp_path / "workspaces",
        runs_root=tmp_path / "runs",
        console_progress_enabled=False,
        context_compaction_enabled=False,
    )

    result = await NanoAgent(config, llm=TodoThenFinishLLM()).run(  # type: ignore[arg-type]
        "https://example.com/repo.git",
        "Inspect the repository.",
    )

    run_dir = config.runs_root / result.run_id
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert "context_checkpoint" not in summary["artifacts"]
    assert not (run_dir / "context_checkpoint.json").exists()
