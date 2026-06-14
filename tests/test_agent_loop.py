import json
from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.context.compactor import CompactionStore, ContextCompactor
from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.hooks.permission import PermissionDeniedError
from nano_agent.hooks.registry import build_default_hooks
from nano_agent.loop import AgentLoop
from nano_agent.models import AgentMessage, LLMResponse, RunSummary, ToolUseRequest
from nano_agent.persistence.message_store import MessageStore
from nano_agent.services.errors import LLMErrorKind, LLMServiceError
from nano_agent.services.llm import LLMClient
from nano_agent.services.retry import RetryPolicy
from nano_agent.tools.base import ToolContext, ToolRegistry, build_default_tool_registry
from nano_agent.tools.run_command import RunCommandTool
from nano_agent.tools.todo import TodoWriteTool


class OneToolUseLLM:
    """测试用 LLM，第一轮请求工具，第二轮结束。"""

    def __init__(self) -> None:
        self.calls = 0  # 记录 LLM 被调用次数。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="call run_command",
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="toolu_1",
                        name="run_command",
                        input={"program": "python3", "args": ["-c", "print('hello', end='')"]},
                    )
                ],
            )
        return LLMResponse(content="end_turn", stop_reason="end_turn")


class InvalidToolUseLLM:
    def __init__(self, tool_name: str, input_data: dict) -> None:
        self.calls = 0
        self.tool_name = tool_name
        self.input_data = input_data

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(id="toolu_invalid", name=self.tool_name, input=self.input_data)
                ],
            )
        return LLMResponse(content="recovered", stop_reason="end_turn")


class RecordingHook(NoOpHook):
    """测试用 hook，记录 loop 扩展点是否被调用。"""

    def __init__(self) -> None:
        self.events: list[str] = []  # 保存 hook 调用事件名称。

    def before_llm_call(self, context, messages, tools):  # type: ignore[no-untyped-def]
        self.events.append("before_llm_call")

    def after_llm_call(self, context, response):  # type: ignore[no-untyped-def]
        self.events.append("after_llm_call")

    def before_tool_call(self, context, tool, tool_use):  # type: ignore[no-untyped-def]
        self.events.append("before_tool_call")

    def after_tool_call(  # type: ignore[no-untyped-def]
        self,
        context,
        tool,
        tool_use,
        result,
        duration_seconds,
    ):
        self.events.append("after_tool_call")
        self.duration_seconds = duration_seconds


class ReminderHook(NoOpHook):
    def before_tool_call(self, context, tool, tool_use):  # type: ignore[no-untyped-def]
        return HookResult(
            injected_messages=[AgentMessage(role="system", content=f"Reminder for {tool_use.name}")]
        )


class PromptTooLongThenFinishLLM:
    """测试用 LLM，首次模拟上下文超限，重试后结束。"""

    def __init__(self) -> None:
        self.calls = 0  # 记录包含失败请求在内的调用次数。
        self.request_sizes: list[int] = []  # 保存每次请求的消息数量。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.request_sizes.append(len(messages))
        if self.calls == 1:
            raise RuntimeError("maximum context length exceeded")
        return LLMResponse(content="recovered", stop_reason="end_turn")


class TransientThenFinishLLM:
    def __init__(self, failures: int, error: LLMServiceError) -> None:
        self.calls = 0
        self.failures = failures
        self.error = error

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return LLMResponse(content="recovered", stop_reason="end_turn")


class TruncatedThenFinishLLM:
    def __init__(self, *, truncated_tool_call: bool = False) -> None:
        self.calls = 0
        self.truncated_tool_call = truncated_tool_call
        self.requests: list[list[AgentMessage]] = []

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.requests.append([message.model_copy(deep=True) for message in messages])
        if self.calls == 1:
            return LLMResponse(
                content="partial response",
                stop_reason="max_tokens",
                provider_stop_reason="length",
                truncated_tool_call=self.truncated_tool_call,
            )
        return LLMResponse(content="continued response", stop_reason="end_turn")


class AlwaysTruncatedLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        return LLMResponse(content=f"partial-{self.calls}", stop_reason="max_tokens")


class AlwaysPromptTooLongLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise LLMServiceError(
            "maximum context length exceeded",
            kind=LLMErrorKind.PROMPT_TOO_LONG,
            status_code=400,
        )


class InvalidResponseThenFinishLLM:
    def __init__(self, failures: int = 1) -> None:
        self.calls = 0  # 记录包含非法响应在内的调用次数。
        self.failures = failures  # 返回非法响应的次数。
        self.requests: list[list[AgentMessage]] = []  # 保存每次请求的消息快照。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.requests.append([message.model_copy(deep=True) for message in messages])
        if self.calls <= self.failures:
            raise LLMServiceError(
                "provider returned invalid tool call arguments",
                kind=LLMErrorKind.INVALID_RESPONSE,
                invalid_tool_name="read_file",
                invalid_tool_arguments_preview='{"path":',
            )
        return LLMResponse(content="recovered", stop_reason="end_turn")


def test_agent_loop_executes_tool_and_records_result(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    llm: LLMClient = OneToolUseLLM()
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    tools = ToolRegistry([RunCommandTool()])
    loop = AgentLoop(config=config, llm=llm, tools=tools, context=context)
    run = RunSummary(run_id="test", repo_url="https://example.com/repo.git")

    result = loop.run(run=run, initial_messages=[AgentMessage(role="user", content="start")])

    assert result.status == "completed"
    assert result.tool_calls[0].tool_name == "run_command"
    assert result.tool_calls[0].success
    assert any(message.role == "tool" for message in result.messages)
    assert capsys.readouterr().out == ""


def test_agent_loop_retries_once_after_reactive_compaction(tmp_path: Path) -> None:
    config = AgentConfig(
        context_max_input_tokens=100_000,
        reactive_keep_recent_messages=2,
    )
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = PromptTooLongThenFinishLLM()
    store = MessageStore(context.run_dir)
    compactor = ContextCompactor(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        store=CompactionStore("test", context.run_dir, store),
        repo_url=context.repo_url,
        workspace_path=context.workspace_path,
    )
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry([]),
        context=context,
        message_store=store,
        compactor=compactor,
    )
    initial = [
        AgentMessage(role="system", content="core"),
        AgentMessage(role="user", content="task"),
        *[
            AgentMessage(role="assistant", content=(f"old-{index} " * 100))
            for index in range(8)
        ],
    ]

    result = loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        initial,
    )

    assert result.status == "completed"
    assert result.llm_call_count == 2
    assert llm.calls == 2
    assert llm.request_sizes[1] < llm.request_sizes[0]
    assert context.current_llm_call_id == "llm-1-reactive-1"
    assert compactor.reactive_compact_attempts == 1


def test_agent_loop_retries_transient_errors_with_exponential_backoff(tmp_path: Path) -> None:
    config = AgentConfig(
        llm_max_transient_retries=3,
        llm_retry_base_seconds=1,
        llm_retry_max_seconds=8,
        llm_retry_jitter_seconds=0,
    )
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = TransientThenFinishLLM(
        2,
        LLMServiceError("rate limited", kind=LLMErrorKind.RATE_LIMIT, status_code=429),
    )
    delays: list[float] = []
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
        retry_policy=RetryPolicy(
            base_seconds=1,
            max_seconds=8,
            jitter_seconds=0,
        ),
        sleeper=delays.append,
    )

    result = loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    assert result.status == "completed"
    assert result.steps == 1
    assert result.llm_call_count == 3
    assert llm.calls == 3
    assert delays == [1, 2]
    assert context.current_llm_call_id == "llm-1-transient-2"


def test_agent_loop_prefers_retry_after_header_delay(tmp_path: Path) -> None:
    config = AgentConfig(llm_max_transient_retries=1)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = TransientThenFinishLLM(
        1,
        LLMServiceError(
            "overloaded",
            kind=LLMErrorKind.OVERLOADED,
            status_code=529,
            retry_after_seconds=3.5,
        ),
    )
    delays: list[float] = []
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
        sleeper=delays.append,
    )

    loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    assert delays == [3.5]


def test_agent_loop_does_not_retry_non_transient_error(tmp_path: Path) -> None:
    config = AgentConfig(llm_max_transient_retries=3)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = TransientThenFinishLLM(
        1,
        LLMServiceError(
            "invalid credentials",
            kind=LLMErrorKind.AUTHENTICATION,
            status_code=401,
        ),
    )
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
        sleeper=lambda _: None,
    )

    with pytest.raises(LLMServiceError) as captured:
        loop.run(
            RunSummary(run_id="test", repo_url=context.repo_url),
            [AgentMessage(role="user", content="start")],
        )

    assert captured.value.kind == LLMErrorKind.AUTHENTICATION
    assert llm.calls == 1


def test_agent_loop_retries_invalid_response_once_with_repair_prompt(
    tmp_path: Path,
) -> None:
    config = AgentConfig()
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = InvalidResponseThenFinishLLM()
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
    )

    result = loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    assert result.status == "completed"
    assert result.llm_call_count == 2
    assert llm.calls == 2
    assert context.current_llm_call_id == "llm-1-invalid_response-1"
    repair_prompt = llm.requests[1][-1]
    assert repair_prompt.role == "system"
    assert "Regenerate the complete next response" in repair_prompt.content
    assert "Do not continue, reuse, or repair fragments" in repair_prompt.content


def test_agent_loop_fails_after_second_invalid_response(tmp_path: Path) -> None:
    config = AgentConfig()
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = InvalidResponseThenFinishLLM(failures=2)
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
    )
    run = RunSummary(run_id="test", repo_url=context.repo_url)

    with pytest.raises(LLMServiceError) as captured:
        loop.run(run, [AgentMessage(role="user", content="start")])

    assert captured.value.kind == LLMErrorKind.INVALID_RESPONSE
    assert llm.calls == 2
    assert run.llm_call_count == 2


def test_agent_loop_continues_after_output_truncation(tmp_path: Path) -> None:
    config = AgentConfig(llm_max_continuations=2)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = TruncatedThenFinishLLM()
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
    )

    result = loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    assert result.status == "completed"
    assert result.steps == 1
    assert result.llm_call_count == 2
    assert context.current_llm_call_id == "llm-1-continuation-1"
    assert [message.role for message in result.messages] == [
        "user",
        "assistant",
        "system",
        "assistant",
    ]
    assert "Continue from where it stopped" in llm.requests[1][-1].content


def test_agent_loop_regenerates_truncated_tool_call(tmp_path: Path) -> None:
    config = AgentConfig(llm_max_continuations=1)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = TruncatedThenFinishLLM(truncated_tool_call=True)
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
    )

    loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    assert "Regenerate the complete tool call" in llm.requests[1][-1].content


def test_agent_loop_fails_after_continuation_limit(tmp_path: Path) -> None:
    config = AgentConfig(llm_max_continuations=1)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = AlwaysTruncatedLLM()
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
    )
    run = RunSummary(run_id="test", repo_url=context.repo_url)

    with pytest.raises(LLMServiceError) as captured:
        loop.run(run, [AgentMessage(role="user", content="start")])

    assert captured.value.kind == LLMErrorKind.OUTPUT_TRUNCATED
    assert run.steps == 1
    assert run.llm_call_count == 2


def test_agent_loop_fails_when_prompt_is_still_too_long_after_reactive_compact(
    tmp_path: Path,
) -> None:
    config = AgentConfig(
        context_max_input_tokens=100_000,
        reactive_keep_recent_messages=2,
    )
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = AlwaysPromptTooLongLLM()
    store = MessageStore(context.run_dir)
    compactor = ContextCompactor(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        store=CompactionStore("test", context.run_dir, store),
        repo_url=context.repo_url,
        workspace_path=context.workspace_path,
    )
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
        message_store=store,
        compactor=compactor,
    )
    initial = [
        AgentMessage(role="system", content="core"),
        AgentMessage(role="user", content="task"),
        *[
            AgentMessage(role="assistant", content=(f"old-{index} " * 100))
            for index in range(8)
        ],
    ]
    run = RunSummary(run_id="test", repo_url=context.repo_url)

    with pytest.raises(LLMServiceError) as captured:
        loop.run(run, initial)

    assert captured.value.kind == LLMErrorKind.PROMPT_TOO_LONG
    assert llm.calls == 2
    assert run.llm_call_count == 2
    assert compactor.reactive_compact_attempts == 1


def test_agent_loop_does_not_retry_when_reactive_compact_cannot_reduce_context(
    tmp_path: Path,
) -> None:
    config = AgentConfig(context_max_input_tokens=100_000)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = AlwaysPromptTooLongLLM()
    store = MessageStore(context.run_dir)
    compactor = ContextCompactor(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        store=CompactionStore("test", context.run_dir, store),
        repo_url=context.repo_url,
        workspace_path=context.workspace_path,
    )
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
        message_store=store,
        compactor=compactor,
    )

    with pytest.raises(LLMServiceError, match="did not reduce"):
        loop.run(
            RunSummary(run_id="test", repo_url=context.repo_url),
            [
                AgentMessage(role="system", content="core"),
                AgentMessage(role="user", content="task"),
            ],
        )

    assert llm.calls == 1


def test_agent_loop_persists_messages_in_protocol_order(tmp_path: Path) -> None:
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    store = MessageStore(context.run_dir)
    loop = AgentLoop(
        config=config,
        llm=OneToolUseLLM(),  # type: ignore[arg-type]
        tools=ToolRegistry([RunCommandTool()]),
        context=context,
        message_store=store,
    )

    loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    persisted = store.load_messages()
    assert [message.role for message in persisted] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    records = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["llm_call_id"] is None
    assert records[1]["llm_call_id"] == "llm-1"
    assert records[-1]["llm_call_id"] == "llm-2"


def test_agent_loop_calls_hooks(tmp_path: Path) -> None:
    llm: LLMClient = OneToolUseLLM()
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    tools = ToolRegistry([RunCommandTool()])
    hook = RecordingHook()
    loop = AgentLoop(config=config, llm=llm, tools=tools, context=context, hooks=[hook])
    run = RunSummary(run_id="test", repo_url="https://example.com/repo.git")

    loop.run(run=run, initial_messages=[AgentMessage(role="user", content="start")])

    assert "before_llm_call" in hook.events
    assert "after_llm_call" in hook.events
    assert "before_tool_call" in hook.events
    assert "after_tool_call" in hook.events
    assert hook.duration_seconds >= 0
    assert context.current_step == 2
    assert context.max_steps == config.max_steps


def test_agent_loop_appends_hook_reminders_after_tool_results(tmp_path: Path) -> None:
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    loop = AgentLoop(
        config=config,
        llm=OneToolUseLLM(),  # type: ignore[arg-type]
        tools=ToolRegistry([RunCommandTool()]),
        context=context,
        hooks=[ReminderHook()],
    )

    result = loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    roles = [message.role for message in result.messages]
    assert roles[:4] == ["user", "assistant", "tool", "system"]
    assert result.messages[3].content == "Reminder for run_command"


def test_default_tool_registry_exposes_metadata(tmp_path: Path) -> None:
    config = AgentConfig(workspace_root=tmp_path)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )

    specs = build_default_tool_registry(context).specs()

    command = next(spec for spec in specs if spec.name == "run_command")
    assert command.category == "execution"
    assert command.requires_workspace
    assert command.is_mutating
    assert any(spec.name == "grep" for spec in specs)
    assert any(spec.name == "finish_run" for spec in specs)
    assert all(spec.name != "bash" for spec in specs)


def test_permission_hook_rejects_unapproved_command(tmp_path: Path) -> None:
    llm: LLMClient = OneToolUseLLM()
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    tools = ToolRegistry([RunCommandTool()])
    loop = AgentLoop(
        config=config,
        llm=llm,
        tools=tools,
        context=context,
        hooks=build_default_hooks(config),
    )
    run = RunSummary(run_id="test", repo_url="https://example.com/repo.git")

    with pytest.raises(PermissionDeniedError):
        loop.run(run=run, initial_messages=[AgentMessage(role="user", content="start")])


def test_permission_hook_allows_command_when_enabled(tmp_path: Path) -> None:
    llm: LLMClient = OneToolUseLLM()
    config = AgentConfig(workspace_root=tmp_path, command_timeout_seconds=5, allow_command=True)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    tools = ToolRegistry([RunCommandTool()])
    loop = AgentLoop(
        config=config,
        llm=llm,
        tools=tools,
        context=context,
        hooks=build_default_hooks(config),
    )
    run = RunSummary(run_id="test", repo_url="https://example.com/repo.git")

    result = loop.run(run=run, initial_messages=[AgentMessage(role="user", content="start")])

    assert result.status == "completed"


def test_todo_write_is_optional_tool() -> None:
    config = AgentConfig()
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=Path("."),
        run_dir=Path(".nano/runs/test"),
        config=config,
    )
    tool = TodoWriteTool()

    result = tool.invoke({"action": "add", "title": "Inspect README"}, context)

    assert result.success
    assert result.data["todos"][0]["title"] == "Inspect README"


def test_agent_loop_returns_invalid_tool_input_to_llm(tmp_path: Path) -> None:
    config = AgentConfig(workspace_root=tmp_path)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = InvalidToolUseLLM("todo_write", {"action": "add", "unexpected": True})
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry([TodoWriteTool()]),
        context=context,
    )

    result = loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    assert result.status == "completed"
    assert not result.tool_calls[0].success
    assert '"error_code": "invalid_input"' in result.messages[-2].content


def test_agent_loop_returns_unknown_tool_to_llm(tmp_path: Path) -> None:
    config = AgentConfig(workspace_root=tmp_path)
    context = ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=config,
    )
    llm = InvalidToolUseLLM("missing_tool", {})
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry(),
        context=context,
    )

    result = loop.run(
        RunSummary(run_id="test", repo_url=context.repo_url),
        [AgentMessage(role="user", content="start")],
    )

    assert result.status == "completed"
    assert result.tool_calls[0].tool_name == "missing_tool"
    assert '"error_code": "tool_not_found"' in result.messages[-2].content
