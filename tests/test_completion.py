from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.loop import AgentLoop
from nano_agent.models import AgentMessage, LLMResponse, RunSummary, ToolUseRequest
from nano_agent.persistence.report_store import ReportStore
from nano_agent.tools.base import ToolContext, ToolRegistry
from nano_agent.tools.finish_run import FinishRunTool
from nano_agent.tools.todo import TodoWriteTool


def make_context(tmp_path: Path, max_steps: int = 5) -> ToolContext:
    """构造支持终止协议的测试运行上下文。"""

    config = AgentConfig(workspace_root=tmp_path, max_steps=max_steps)
    return ToolContext(
        run_id="run-1",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "run-1",
        config=config,
    )


class TodoThenCompleteLLM:
    """先执行一个工具，再提交 completed 报告。"""

    def __init__(self) -> None:
        self.calls = 0  # 记录模型调用次数。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="verify-1",
                        name="todo_write",
                        input={"action": "add", "title": "Verified"},
                    )
                ],
            )
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="finish-1",
                    name="finish_run",
                    input={
                        "status": "completed",
                        "problem": "A repository task required verification.",
                        "root_cause": "The target behavior needed confirmation.",
                        "resolution": "The behavior was checked successfully.",
                        "verification_summary": "Verification completed successfully.",
                    },
                )
            ],
        )


class BlockedLLM:
    """直接提交合法 blocked 报告。"""

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="finish-blocked",
                    name="finish_run",
                    input={
                        "status": "blocked",
                        "problem": "Tests require unavailable credentials.",
                        "root_cause": "The external service rejected unauthenticated access.",
                        "resolution": "Stopped before making unverifiable changes.",
                        "blockers": ["Required service credentials are unavailable."],
                    },
                )
            ],
        )


class InvalidEndTurnLLM:
    """持续使用普通 end_turn，触发协议失败。"""

    def __init__(self) -> None:
        self.calls = 0  # 记录模型是否获得一次纠正机会。
        self.saw_correction = False  # 第二轮是否看到终止协议纠正消息。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.saw_correction = self.saw_correction or any(
            "Plain end_turn does not determine run status" in message.content
            for message in messages
        )
        return LLMResponse(content="done", stop_reason="end_turn")


class NonExclusiveFinishLLM:
    """首次将 finish_run 与其他工具并发提交，随后单独重试。"""

    def __init__(self) -> None:
        self.calls = 0  # 记录非独占 finish_run 后的继续调用。
        self.saw_validation_error = False  # 是否收到 invalid_completion 工具结果。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.saw_validation_error = self.saw_validation_error or any(
            message.role == "tool" and "invalid_completion" in message.content
            for message in messages
        )
        if self.calls == 1:
            return LLMResponse(
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="finish-non-exclusive",
                        name="finish_run",
                        input={
                            "status": "completed",
                            "problem": "Task",
                            "root_cause": "Cause",
                            "resolution": "Resolution",
                            "verification_summary": "Claimed verification.",
                        },
                    ),
                    ToolUseRequest(
                        id="todo-alongside-finish",
                        name="todo_write",
                        input={"action": "add", "title": "Unexpected extra call"},
                    ),
                ],
            )
        return LLMResponse(
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="finish-failed",
                    name="finish_run",
                    input={
                        "status": "completed",
                        "problem": "Task",
                        "root_cause": "Cause",
                        "resolution": "Submitted finish_run as the only tool call.",
                        "verification_summary": "Verification completed.",
                    },
                )
            ],
        )


def run_with_completion(tmp_path: Path, llm) -> RunSummary:  # type: ignore[no-untyped-def]
    """运行包含 finish_run 的最小 AgentLoop。"""

    context = make_context(tmp_path)
    loop = AgentLoop(
        config=context.config,
        llm=llm,
        tools=ToolRegistry([TodoWriteTool(), FinishRunTool()]),
        context=context,
    )
    return loop.run(
        RunSummary(run_id=context.run_id, repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )


def test_completed_report_is_accepted_without_tool_call_ids(tmp_path: Path) -> None:
    result = run_with_completion(tmp_path, TodoThenCompleteLLM())

    assert result.status == "completed"
    assert result.completion_report is not None
    assert result.completion_report.status == "completed"
    assert result.completion_report.verification_summary == "Verification completed successfully."


def test_blocked_report_maps_to_blocked_run_status(tmp_path: Path) -> None:
    result = run_with_completion(tmp_path, BlockedLLM())

    assert result.status == "blocked"
    assert result.completion_report is not None
    assert result.completion_report.blockers


def test_plain_end_turn_gets_one_correction_then_fails(tmp_path: Path) -> None:
    llm = InvalidEndTurnLLM()

    result = run_with_completion(tmp_path, llm)

    assert result.status == "failed"
    assert llm.calls == 2
    assert llm.saw_correction
    assert result.completion_report is not None
    assert "ended twice" in result.completion_report.resolution


def test_finish_run_must_be_the_only_tool_call_and_can_be_corrected(tmp_path: Path) -> None:
    llm = NonExclusiveFinishLLM()

    result = run_with_completion(tmp_path, llm)

    assert result.status == "completed"
    assert llm.saw_validation_error
    assert not result.tool_calls[0].success
    assert result.tool_calls[0].tool_name == "finish_run"


def test_report_store_renders_uniform_markdown(tmp_path: Path) -> None:
    result = run_with_completion(tmp_path, TodoThenCompleteLLM())
    result.finished_at = result.started_at

    path = ReportStore().save(tmp_path, result, result.completion_report)  # type: ignore[arg-type]
    content = path.read_text(encoding="utf-8")

    assert content.startswith("# nanoAgent Run Report")
    assert "## Root Cause" in content
    assert "## Verification" in content
    assert "**Status:** completed" in content
