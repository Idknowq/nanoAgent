from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.hooks.pipeline import HookPipeline
from nano_agent.models import AgentMessage, LLMResponse, ToolUseRequest
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult


class PipelineTool(RuntimeTool):
    """Minimal runtime tool used by pipeline tests."""

    name = "pipeline_tool"
    description = "Pipeline test tool."

    async def run(self, input_data, context):  # type: ignore[no-untyped-def]
        del input_data, context
        return ToolResult(success=True, summary="ok", data={})


class RecordingPipelineHook(NoOpHook):
    """Hook that records ordered pipeline callbacks and injects messages."""

    def __init__(self, label: str, events: list[str]) -> None:
        self.label = label  # Stable identifier added to the shared event log.
        self.events = events  # Shared event log used by assertions.

    async def before_llm_call(self, context, messages, tools):  # type: ignore[no-untyped-def]
        del context, messages, tools
        self.events.append(f"{self.label}:before_llm")
        return HookResult(
            injected_messages=[AgentMessage(role="system", content=f"{self.label}:before_llm")]
        )

    async def after_llm_call(self, context, response):  # type: ignore[no-untyped-def]
        del context, response
        self.events.append(f"{self.label}:after_llm")
        return HookResult(
            injected_messages=[AgentMessage(role="system", content=f"{self.label}:after_llm")]
        )

    async def before_tool_call(self, context, tool, tool_use):  # type: ignore[no-untyped-def]
        del context, tool, tool_use
        self.events.append(f"{self.label}:before_tool")
        return HookResult(
            injected_messages=[AgentMessage(role="system", content=f"{self.label}:before_tool")]
        )

    async def after_tool_call(  # type: ignore[no-untyped-def]
        self,
        context,
        tool,
        tool_use,
        result,
        duration_seconds,
    ):
        del context, tool, tool_use, result, duration_seconds
        self.events.append(f"{self.label}:after_tool")
        return HookResult(
            injected_messages=[AgentMessage(role="system", content=f"{self.label}:after_tool")]
        )

    async def on_error(self, context, error):  # type: ignore[no-untyped-def]
        del context, error
        self.events.append(f"{self.label}:on_error")


class DenyingHook(NoOpHook):
    """Hook that rejects a tool call before invocation."""

    async def before_tool_call(self, context, tool, tool_use):  # type: ignore[no-untyped-def]
        del context, tool, tool_use
        raise PermissionError("denied")


class FailingErrorHook(NoOpHook):
    """Hook whose error handler fails and must not replace the original error."""

    async def on_error(self, context, error):  # type: ignore[no-untyped-def]
        del context, error
        raise RuntimeError("error hook failed")


def make_context(tmp_path: Path) -> ToolContext:
    """Build a minimal tool context for pipeline tests."""
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=AgentConfig(workspace_root=tmp_path),
    )


async def test_hook_pipeline_preserves_order_and_injected_messages(tmp_path: Path) -> None:
    events: list[str] = []
    context = make_context(tmp_path)
    pipeline = HookPipeline(
        [
            RecordingPipelineHook("a", events),
            RecordingPipelineHook("b", events),
        ]
    )
    tool = PipelineTool()
    tool_use = ToolUseRequest(id="toolu_1", name=tool.name, input={})

    before_llm = await pipeline.before_llm_call(context, [], [])
    after_llm = await pipeline.after_llm_call(
        context,
        LLMResponse(content="done", stop_reason="end_turn"),
    )
    before_tool = await pipeline.before_tool_call(context, tool, tool_use)
    after_tool = await pipeline.after_tool_call(
        context,
        tool,
        tool_use,
        ToolResult(success=True, summary="ok", data={}),
        0.1,
    )

    assert events == [
        "a:before_llm",
        "b:before_llm",
        "a:after_llm",
        "b:after_llm",
        "a:before_tool",
        "b:before_tool",
        "a:after_tool",
        "b:after_tool",
    ]
    assert [message.content for message in before_llm] == ["a:before_llm", "b:before_llm"]
    assert [message.content for message in after_llm] == ["a:after_llm", "b:after_llm"]
    assert [message.content for message in before_tool] == ["a:before_tool", "b:before_tool"]
    assert [message.content for message in after_tool] == ["a:after_tool", "b:after_tool"]


async def test_hook_pipeline_propagates_permission_denial(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    tool = PipelineTool()
    tool_use = ToolUseRequest(id="toolu_1", name=tool.name, input={})

    with pytest.raises(PermissionError, match="denied"):
        await HookPipeline([DenyingHook()]).before_tool_call(context, tool, tool_use)


async def test_hook_pipeline_on_error_does_not_replace_original_error(tmp_path: Path) -> None:
    events: list[str] = []
    context = make_context(tmp_path)
    original = ValueError("original")
    pipeline = HookPipeline(
        [
            FailingErrorHook(),
            RecordingPipelineHook("after", events),
        ]
    )

    await pipeline.on_error(context, original)

    assert events == ["after:on_error"]
