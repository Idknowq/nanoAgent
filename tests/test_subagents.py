import json
from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.models import LLMResponse, ToolUseRequest
from nano_agent.subagents.manager import SubagentManager
from nano_agent.subagents.models import (
    SubagentErrorKind,
    SubagentRequest,
    SubagentState,
    SubagentStatus,
)
from nano_agent.tools.base import ToolContext, ToolRegistry
from nano_agent.tools.delegate_task import DelegateTaskTool
from nano_agent.tools.grep import GrepTool
from nano_agent.tools.list_files import ListFilesTool
from nano_agent.tools.read_file import ReadFileTool


class SuccessfulSubagentLLM:
    def __init__(self) -> None:
        self.requests = []
        self.tool_names: list[set[str]] = []

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.requests.append([message.model_copy(deep=True) for message in messages])
        self.tool_names.append({tool.name for tool in tools})
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="finish-subagent",
                    name="finish_run",
                    input={
                        "status": "completed",
                        "problem": "Inspect the delegated scope.",
                        "root_cause": "The requested evidence was located.",
                        "resolution": "Found the requested implementation detail.",
                        "verification_summary": "Reviewed the available repository files.",
                    },
                )
            ],
        )


class InvalidEndTurnSubagentLLM:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return LLMResponse(content="done", stop_reason="end_turn")


class ExploreThenFinalizeSubagentLLM:
    def __init__(self) -> None:
        self.calls = 0  # 记录子 Agent 已完成的逻辑步骤。
        self.final_tools: set[str] = set()  # 最后一步向模型暴露的工具名称。
        self.saw_final_prompt = False  # 最后一步是否收到强制总结提示。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="read-evidence",
                        name="read_file",
                        input={"path": "evidence.txt"},
                    )
                ],
            )
        self.final_tools = {tool.name for tool in tools}
        self.saw_final_prompt = any(
            "final response opportunity" in message.content for message in messages
        )
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="finish-finalization",
                    name="finish_run",
                    input={
                        "status": "blocked",
                        "problem": "The delegated investigation is incomplete.",
                        "root_cause": "The finalization budget was reached.",
                        "resolution": "Collected partial evidence from evidence.txt.",
                        "blockers": ["Further investigation requires another delegation."],
                    },
                )
            ],
        )


class RejectFinalizationThenCorrectSubagentLLM:
    def __init__(self) -> None:
        self.calls = 0  # 记录调查、错误总结和协议纠正调用。
        self.final_tool_sets: list[set[str]] = []  # 保存最终阶段暴露的工具集合。
        self.saw_correction_prompt = False  # 是否收到最终协议纠正提示。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="read-evidence",
                        name="read_file",
                        input={"path": "evidence.txt"},
                    )
                ],
            )
        self.final_tool_sets.append({tool.name for tool in tools})
        if self.calls == 2:
            return LLMResponse(
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="invalid-final-read",
                        name="read_file",
                        input={"path": "evidence.txt"},
                    )
                ],
            )
        self.saw_correction_prompt = any(
            "only protocol-correction call" in message.content for message in messages
        )
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="corrected-finish",
                    name="finish_run",
                    input={
                        "status": "blocked",
                        "problem": "The delegated investigation is incomplete.",
                        "root_cause": "The investigation budget was exhausted.",
                        "resolution": "Returned the reliable partial evidence.",
                        "blockers": ["More file inspection is required."],
                    },
                )
            ],
        )


class RejectBothFinalizationCallsSubagentLLM:
    def __init__(self) -> None:
        self.calls = 0  # 记录最终协议持续失败前的调用次数。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id=f"invalid-read-{self.calls}",
                    name="read_file",
                    input={"path": "evidence.txt"},
                )
            ],
        )


class BlockedSubagentLLM:
    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="finish-blocked-subagent",
                    name="finish_run",
                    input={
                        "status": "blocked",
                        "problem": "The delegated task needs unavailable input.",
                        "root_cause": "Required credentials were not provided.",
                        "resolution": "Stopped without making unsupported claims.",
                        "blockers": ["Credentials are unavailable."],
                    },
                )
            ],
        )


def make_parent_context(tmp_path: Path, config: AgentConfig) -> ToolContext:
    return ToolContext(
        run_id="parent-run",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "parent-run",
        config=config,
        current_step=7,
        current_llm_call_id="llm-7",
    )


def make_manager(
    tmp_path: Path,
    llm,
    *,
    config: AgentConfig | None = None,
) -> tuple[SubagentManager, ToolContext]:
    active_config = config or AgentConfig(
        workspace_root=tmp_path,
        runs_root=tmp_path / "runs",
        console_progress_enabled=False,
        llm_calls_enabled=False,
        audit_enabled=False,
    )
    context = make_parent_context(tmp_path, active_config)
    tools = ToolRegistry([ListFilesTool(), GrepTool(), ReadFileTool()])
    manager = SubagentManager(
        config=active_config,
        llm=llm,
        parent_context=context,
        parent_tools=tools,
        hooks_factory=lambda: [],
    )
    return manager, context


def test_subagent_state_rejects_invalid_terminal_transition() -> None:
    state = SubagentState(
        subagent_id="subagent-1",
        parent_run_id="parent",
        status=SubagentStatus.CREATED,
        task="inspect",
        allowed_tools=(),
    )

    state.transition(SubagentStatus.RUNNING)
    state.transition(SubagentStatus.SUCCEEDED)

    with pytest.raises(ValueError, match="succeeded -> running"):
        state.transition(SubagentStatus.RUNNING)


def test_subagent_has_isolated_messages_tools_and_counters(tmp_path: Path) -> None:
    llm = SuccessfulSubagentLLM()
    manager, parent_context = make_manager(tmp_path, llm)
    request = SubagentRequest(
        task="Find the persistence implementation.",
        context="Inspect only the persistence package.",
        allowed_tools=("read_file",),
        max_steps=3,
        max_llm_calls=3,
    )

    result = manager.run(request)

    assert result.status == SubagentStatus.SUCCEEDED
    assert result.output == "Found the requested implementation detail."
    assert result.steps_used == 1
    assert result.llm_calls_used == 1
    assert llm.tool_names == [{"read_file", "finish_run"}]
    sent_content = "\n".join(message.content for message in llm.requests[0])
    assert "Inspect only the persistence package." in sent_content
    assert "parent conversation" in sent_content
    assert "llm-7" not in sent_content
    assert parent_context.current_step == 7
    assert parent_context.current_llm_call_id == "llm-7"


def test_subagent_persists_lifecycle_and_result(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path, SuccessfulSubagentLLM())

    result = manager.run(
        SubagentRequest(
            task="Inspect files.",
            allowed_tools=("list_files",),
            max_steps=3,
            max_llm_calls=3,
        )
    )

    run_dir = Path(result.run_dir)
    state = json.loads((run_dir / "subagent.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (run_dir / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    messages = (run_dir / "messages.jsonl").read_text(encoding="utf-8")
    persisted_result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    assert state["status"] == "succeeded"
    assert state["parent_run_id"] == "parent-run"
    assert [event["status"] for event in events] == ["created", "running", "succeeded"]
    assert "Found the requested implementation detail." in messages
    assert persisted_result["completion_report"]["status"] == "completed"
    assert summary["status"] == "completed"
    assert summary["llm_call_count"] == 1


def test_subagent_id_survives_manager_recreation(tmp_path: Path) -> None:
    first_manager, _ = make_manager(tmp_path, SuccessfulSubagentLLM())
    first = first_manager.run(
        SubagentRequest(
            task="First inspection.",
            max_steps=3,
            max_llm_calls=3,
        )
    )
    second_manager, _ = make_manager(tmp_path, SuccessfulSubagentLLM())

    second = second_manager.run(
        SubagentRequest(
            task="Second inspection.",
            max_steps=3,
            max_llm_calls=3,
        )
    )

    assert first.subagent_id == "subagent-1"
    assert second.subagent_id == "subagent-2"
    assert Path(first.run_dir).is_dir()
    assert Path(second.run_dir).is_dir()


def test_blocked_subagent_preserves_blocked_status(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path, BlockedSubagentLLM())

    result = manager.run(
        SubagentRequest(
            task="Inspect protected service.",
            max_steps=3,
            max_llm_calls=3,
        )
    )

    assert result.status == SubagentStatus.BLOCKED
    assert result.error_kind == SubagentErrorKind.BLOCKED
    state = json.loads(
        (Path(result.run_dir) / "subagent.json").read_text(encoding="utf-8")
    )
    assert state["status"] == "blocked"


def test_subagent_tools_must_be_available_to_parent(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path, SuccessfulSubagentLLM())

    with pytest.raises(ValueError, match="edit_file"):
        manager.run(
            SubagentRequest(
                task="Edit a file.",
                allowed_tools=("edit_file",),
                max_steps=3,
                max_llm_calls=3,
            )
        )


def test_subagent_manager_enforces_configured_budgets(tmp_path: Path) -> None:
    config = AgentConfig(
        workspace_root=tmp_path,
        runs_root=tmp_path / "runs",
        console_progress_enabled=False,
        llm_calls_enabled=False,
        audit_enabled=False,
        subagent_max_steps=2,
    )
    manager, _ = make_manager(tmp_path, SuccessfulSubagentLLM(), config=config)

    with pytest.raises(ValueError, match="max_steps"):
        manager.run(
            SubagentRequest(
                task="Inspect files.",
                max_steps=3,
                max_llm_calls=3,
            )
        )


def test_subagent_llm_call_limit_returns_structured_failure(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path, InvalidEndTurnSubagentLLM())

    result = manager.run(
        SubagentRequest(
            task="Inspect files.",
            max_steps=5,
            max_llm_calls=1,
        )
    )

    assert result.status == SubagentStatus.FAILED
    assert result.error_kind == SubagentErrorKind.LLM_CALL_LIMIT
    assert result.llm_calls_used == 1
    assert "max_llm_calls=1" in (result.error or "")


def test_subagent_step_limit_returns_structured_failure(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path, InvalidEndTurnSubagentLLM())

    result = manager.run(
        SubagentRequest(
            task="Inspect files.",
            max_steps=1,
            max_llm_calls=3,
        )
    )

    assert result.status == SubagentStatus.FAILED
    assert result.error_kind == SubagentErrorKind.STEP_LIMIT
    assert result.steps_used == 1


def test_subagent_reserves_last_step_for_finish_run(tmp_path: Path) -> None:
    (tmp_path / "evidence.txt").write_text("evidence", encoding="utf-8")
    llm = ExploreThenFinalizeSubagentLLM()
    manager, _ = make_manager(tmp_path, llm)

    result = manager.run(
        SubagentRequest(
            task="Inspect evidence and summarize.",
            allowed_tools=("read_file",),
            max_steps=2,
            max_llm_calls=3,
        )
    )

    assert result.status == SubagentStatus.BLOCKED
    assert result.error == "Collected partial evidence from evidence.txt."
    assert llm.calls == 2
    assert llm.final_tools == {"finish_run"}
    assert llm.saw_final_prompt


def test_subagent_corrects_invalid_finalization_once(tmp_path: Path) -> None:
    (tmp_path / "evidence.txt").write_text("evidence", encoding="utf-8")
    llm = RejectFinalizationThenCorrectSubagentLLM()
    manager, _ = make_manager(tmp_path, llm)

    result = manager.run(
        SubagentRequest(
            task="Inspect evidence and summarize.",
            allowed_tools=("read_file",),
            max_steps=2,
            max_llm_calls=4,
        )
    )

    assert result.status == SubagentStatus.BLOCKED
    assert result.error == "Returned the reliable partial evidence."
    assert result.steps_used == 2
    assert result.llm_calls_used == 3
    assert llm.final_tool_sets == [{"finish_run"}, {"finish_run"}]
    assert llm.saw_correction_prompt


def test_subagent_fails_after_invalid_finalization_correction(tmp_path: Path) -> None:
    (tmp_path / "evidence.txt").write_text("evidence", encoding="utf-8")
    llm = RejectBothFinalizationCallsSubagentLLM()
    manager, _ = make_manager(tmp_path, llm)

    result = manager.run(
        SubagentRequest(
            task="Inspect evidence and summarize.",
            allowed_tools=("read_file",),
            max_steps=1,
            max_llm_calls=3,
        )
    )

    assert result.status == SubagentStatus.FAILED
    assert result.error_kind == SubagentErrorKind.STEP_LIMIT
    assert result.steps_used == 1
    assert result.llm_calls_used == 2
    assert "one protocol-correction call" in (result.error or "")


def test_delegate_task_rejects_recursive_delegation(tmp_path: Path) -> None:
    manager, context = make_manager(tmp_path, SuccessfulSubagentLLM())
    context.subagent_id = "subagent-existing"
    context.delegation_depth = 1
    tool = DelegateTaskTool(manager)

    result = tool.invoke({"task": "Create another subagent."}, context)

    assert not result.success
    assert result.error_code == "recursive_delegation_denied"


def test_manager_rejects_recursive_delegation_without_tool_boundary(tmp_path: Path) -> None:
    manager, context = make_manager(tmp_path, SuccessfulSubagentLLM())
    context.subagent_id = "subagent-existing"
    context.delegation_depth = 1

    with pytest.raises(ValueError, match="cannot create"):
        manager.run(
            SubagentRequest(
                task="Create another subagent.",
                max_steps=3,
                max_llm_calls=3,
            )
        )


def test_delegate_task_returns_structured_subagent_result(tmp_path: Path) -> None:
    manager, context = make_manager(tmp_path, SuccessfulSubagentLLM())
    tool = DelegateTaskTool(manager)

    result = tool.invoke(
        {
            "task": "Inspect files.",
            "allowed_tools": ["list_files"],
            "max_steps": 3,
            "max_llm_calls": 3,
        },
        context,
    )

    assert result.success
    assert result.data["subagent_result"]["status"] == "succeeded"
    assert result.data["subagent_result"]["parent_run_id"] == "parent-run"
    assert "completion_report" not in result.data["subagent_result"]
    assert result.data["subagent_result"]["result_path"] == "result.json"
