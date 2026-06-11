import json
from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.hooks.audit import AuditHook
from nano_agent.loop import AgentLoop
from nano_agent.models import AgentMessage, LLMResponse, RunSummary, ToolUseRequest
from nano_agent.tools.base import ToolContext, ToolRegistry, ToolResult
from nano_agent.tools.edit_file import EditFileTool
from nano_agent.tools.todo import TodoWriteTool


def make_context(tmp_path: Path, *, run_dir: Path | None = None) -> ToolContext:
    return ToolContext(
        run_id="run-1",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=run_dir or tmp_path / "runs" / "run-1",
        config=AgentConfig(workspace_root=tmp_path, runs_root=tmp_path / "runs"),
        current_step=2,
        max_steps=20,
    )


def read_records(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_audit_hook_writes_successful_tool_call(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    hook = AuditHook()
    tool = TodoWriteTool()
    tool_use = ToolUseRequest(
        id="call-1",
        name=tool.name,
        input={"action": "add", "title": "检查 README"},
    )
    result = tool.invoke(tool_use.input, context)

    hook.after_tool_call(context, tool, tool_use, result, 0.125)

    records = read_records(context.run_dir / "audit.jsonl")
    assert len(records) == 1
    assert records[0]["run_id"] == "run-1"
    assert records[0]["step"] == 2
    assert records[0]["tool_call_id"] == "call-1"
    assert records[0]["tool_name"] == "todo_write"
    assert records[0]["approval_level"] == "read"
    assert "检查 README" in records[0]["input_summary"]
    assert records[0]["success"]
    assert records[0]["duration_seconds"] == 0.125


def test_audit_hook_appends_failure_record(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    hook = AuditHook()
    tool = TodoWriteTool()
    tool_use = ToolUseRequest(id="call-1", name=tool.name, input={"action": "complete"})
    failure = ToolResult.failure(code="invalid_input", message="todo id is required")

    hook.after_tool_call(context, tool, tool_use, failure, 0.01)
    hook.after_tool_call(context, tool, tool_use, failure, 0.02)

    records = read_records(context.run_dir / "audit.jsonl")
    assert len(records) == 2
    assert not records[0]["success"]
    assert records[0]["error_code"] == "invalid_input"
    assert records[0]["error_message"] == "todo id is required"
    assert records[1]["duration_seconds"] == 0.02


def test_audit_hook_truncates_large_input_summary(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    hook = AuditHook(max_input_chars=100)
    tool = TodoWriteTool()
    tool_use = ToolUseRequest(
        id="call-1",
        name=tool.name,
        input={"action": "add", "title": "x" * 200},
    )

    hook.after_tool_call(
        context,
        tool,
        tool_use,
        ToolResult(success=True, summary="ok"),
        0.01,
    )

    summary = read_records(context.run_dir / "audit.jsonl")[0]["input_summary"]
    assert len(summary) == 100
    assert summary.endswith("...[truncated]")


def test_audit_hook_uses_tool_specific_input_redaction(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    hook = AuditHook()
    tool = EditFileTool()
    old_text = "sensitive old source"
    new_text = "sensitive new source"
    tool_use = ToolUseRequest(
        id="call-1",
        name=tool.name,
        input={
            "path": "app.py",
            "old_text": old_text,
            "new_text": new_text,
            "expected_replacements": 1,
        },
    )

    hook.after_tool_call(
        context,
        tool,
        tool_use,
        ToolResult(success=True, summary="edited"),
        0.01,
    )

    summary = read_records(context.run_dir / "audit.jsonl")[0]["input_summary"]
    redacted = json.loads(summary)
    assert old_text not in summary
    assert new_text not in summary
    assert redacted == {
        "expected_replacements": 1,
        "new_text_chars": len(new_text),
        "old_text_chars": len(old_text),
        "path": "app.py",
    }


def test_audit_hook_write_failure_does_not_raise(tmp_path: Path) -> None:
    blocked_run_dir = tmp_path / "blocked"
    blocked_run_dir.write_text("not a directory", encoding="utf-8")
    context = make_context(tmp_path, run_dir=blocked_run_dir)
    hook = AuditHook()
    tool = TodoWriteTool()
    tool_use = ToolUseRequest(id="call-1", name=tool.name, input={"action": "add"})

    hook.after_tool_call(
        context,
        tool,
        tool_use,
        ToolResult(success=True, summary="ok"),
        0.01,
    )

    assert hook.write_errors
    errors = hook.write_errors
    errors.append("external mutation")
    assert "external mutation" not in hook.write_errors


def test_audit_hook_rejects_invalid_input_limit() -> None:
    with pytest.raises(ValueError, match="at least 100"):
        AuditHook(max_input_chars=99)


class OneTodoLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="call-1",
                        name="todo_write",
                        input={"action": "add", "title": "Inspect repository"},
                    )
                ],
            )
        return LLMResponse(content="done", stop_reason="end_turn")


def test_agent_loop_writes_audit_file_for_actual_tool_calls(tmp_path: Path) -> None:
    config = AgentConfig(workspace_root=tmp_path, runs_root=tmp_path / "runs")
    context = make_context(tmp_path)
    loop = AgentLoop(
        config=config,
        llm=OneTodoLLM(),  # type: ignore[arg-type]
        tools=ToolRegistry([TodoWriteTool()]),
        context=context,
        hooks=[AuditHook()],
    )

    result = loop.run(
        RunSummary(run_id=context.run_id, repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    records = read_records(context.run_dir / "audit.jsonl")
    assert result.status == "succeeded"
    assert len(result.tool_calls) == 1
    assert len(records) == 1
    assert records[0]["step"] == 1
    assert records[0]["tool_name"] == "todo_write"
