import asyncio
import time
from types import SimpleNamespace

from openai import AsyncOpenAI

import pytest

from nano_agent.models import AgentMessage, LLMStopReason
from nano_agent.services.errors import LLMErrorKind, LLMServiceError, normalize_llm_error
from nano_agent.services.openai_compatible import OpenAICompatibleLLMClient
from nano_agent.tools.base import ToolRegistry
from nano_agent.tools.todo import TodoWriteTool


class FakeCompletions:
    """测试用 completions 对象，记录请求并返回固定 tool_call。"""

    def __init__(self) -> None:
        self.last_request = None  # 保存最近一次 create 调用参数。

    async def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_request = kwargs
        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(
                name="todo_write", arguments='{"action":"add","title":"Inspect"}'
            ),
        )
        message = SimpleNamespace(content=None, tool_calls=[tool_call])
        choice = SimpleNamespace(message=message, finish_reason="tool_calls")
        usage = SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=5,
            total_tokens=17,
            prompt_cache_hit_tokens=3,
            prompt_tokens_details=SimpleNamespace(cached_tokens=2),
        )
        return SimpleNamespace(choices=[choice], model="deepseek-test", usage=usage)


class FakeOpenAI:
    """测试用 OpenAI-compatible client。"""

    def __init__(self) -> None:
        self.completions = FakeCompletions()  # 保存 fake completions 入口。
        self.chat = SimpleNamespace(completions=self.completions)


async def test_openai_compatible_client_parses_tool_calls() -> None:
    fake = FakeOpenAI()
    client = OpenAICompatibleLLMClient(  # type: ignore[arg-type]
        client=fake,
        model="deepseek-test",
        temperature=0.0,
        max_output_tokens=32_768,
        thinking_enabled=False,
    )
    tools = ToolRegistry([TodoWriteTool()]).specs()

    response = await client.complete([AgentMessage(role="user", content="start")], tools)

    assert response.stop_reason == "tool_use"
    assert response.provider_stop_reason == "tool_calls"
    assert response.tool_uses[0].name == "todo_write"
    assert response.tool_uses[0].input["title"] == "Inspect"
    assert response.model == "deepseek-test"
    assert response.usage is not None
    assert response.usage.total_tokens == 17
    assert response.usage.cached_tokens == 3
    assert fake.completions.last_request["model"] == "deepseek-test"
    assert fake.completions.last_request["temperature"] == 0.0
    assert fake.completions.last_request["max_tokens"] == 32_768
    assert fake.completions.last_request["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert fake.completions.last_request["tools"][0]["function"]["parameters"]["required"] == [
        "action"
    ]


async def test_openai_message_conversion_preserves_assistant_tool_calls() -> None:
    client = OpenAICompatibleLLMClient(client=AsyncOpenAI(api_key="test"), model="test")
    message = AgentMessage(
        role="assistant",
        content="call tool",
        tool_uses=[
            {
                "id": "call_1",
                "name": "todo_write",
                "input": {"action": "add", "title": "Inspect"},
            }
        ],
    )

    converted = client._to_openai_messages([message])  # noqa: SLF001

    assert converted[0]["tool_calls"][0]["function"]["name"] == "todo_write"


@pytest.mark.parametrize(
    ("provider_reason", "expected"),
    [
        ("stop", LLMStopReason.END_TURN),
        ("tool_calls", LLMStopReason.TOOL_USE),
        ("length", LLMStopReason.MAX_TOKENS),
        ("content_filter", LLMStopReason.CONTENT_FILTER),
        ("unexpected", LLMStopReason.UNKNOWN),
    ],
)
async def test_openai_stop_reason_mapping(provider_reason: str, expected: LLMStopReason) -> None:
    assert OpenAICompatibleLLMClient._normalize_stop_reason(provider_reason) == expected  # noqa: SLF001


async def test_openai_client_marks_truncated_invalid_tool_call() -> None:
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="todo_write", arguments='{"action":'),
    )
    parsed, truncated = OpenAICompatibleLLMClient._parse_tool_calls(  # noqa: SLF001
        [tool_call],
        stop_reason=LLMStopReason.MAX_TOKENS,
    )

    assert parsed == []
    assert truncated


async def test_openai_client_records_bounded_invalid_tool_call_arguments() -> None:
    arguments = '{"action":"' + ("x" * 3_000)
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="todo_write", arguments=arguments),
    )

    with pytest.raises(LLMServiceError) as captured:
        OpenAICompatibleLLMClient._parse_tool_calls(  # noqa: SLF001
            [tool_call],
            stop_reason=LLMStopReason.TOOL_USE,
        )

    assert captured.value.kind == LLMErrorKind.INVALID_RESPONSE
    assert captured.value.invalid_tool_name == "todo_write"
    assert captured.value.invalid_tool_arguments_preview.startswith('{"action":"')
    assert captured.value.invalid_tool_arguments_preview.endswith("...[truncated]")
    assert len(captured.value.invalid_tool_arguments_preview) == 2_000


async def test_openai_client_retries_insufficient_system_resource() -> None:
    class ResourceLimitedCompletions:
        async def create(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            message = SimpleNamespace(content="", tool_calls=[])
            choice = SimpleNamespace(
                message=message,
                finish_reason="insufficient_system_resource",
            )
            return SimpleNamespace(choices=[choice], model="deepseek-test", usage=None)

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=ResourceLimitedCompletions())
    )
    client = OpenAICompatibleLLMClient(client=fake, model="deepseek-test")  # type: ignore[arg-type]

    with pytest.raises(LLMServiceError) as captured:
        await client.complete([AgentMessage(role="user", content="start")], [])

    assert captured.value.kind == LLMErrorKind.OVERLOADED
    assert captured.value.retryable


async def test_openai_client_wait_does_not_block_event_loop() -> None:
    class SlowCompletions:
        async def create(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            await asyncio.sleep(0.2)
            message = SimpleNamespace(content="done", tool_calls=[])
            choice = SimpleNamespace(message=message, finish_reason="stop")
            return SimpleNamespace(choices=[choice], model="deepseek-test", usage=None)

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SlowCompletions()))
    client = OpenAICompatibleLLMClient(client=fake, model="deepseek-test")  # type: ignore[arg-type]

    started = time.monotonic()
    task = asyncio.create_task(client.complete([AgentMessage(role="user", content="start")], []))
    await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    elapsed = time.monotonic() - started
    response = await task

    assert elapsed < 0.15
    assert response.stop_reason == LLMStopReason.END_TURN


@pytest.mark.parametrize(
    ("status_code", "message", "expected"),
    [
        (429, "rate limited", LLMErrorKind.RATE_LIMIT),
        (529, "overloaded", LLMErrorKind.OVERLOADED),
        (500, "server error", LLMErrorKind.OVERLOADED),
        (503, "unavailable", LLMErrorKind.OVERLOADED),
        (401, "unauthorized", LLMErrorKind.AUTHENTICATION),
        (400, "maximum context length exceeded", LLMErrorKind.PROMPT_TOO_LONG),
        (400, "invalid request", LLMErrorKind.INVALID_REQUEST),
        (402, "insufficient balance", LLMErrorKind.INVALID_REQUEST),
        (422, "invalid parameters", LLMErrorKind.INVALID_REQUEST),
    ],
)
async def test_llm_error_normalization(
    status_code: int,
    message: str,
    expected: LLMErrorKind,
) -> None:
    error = RuntimeError(message)
    error.status_code = status_code  # type: ignore[attr-defined]

    normalized = normalize_llm_error(error)

    assert isinstance(normalized, LLMServiceError)
    assert normalized.kind == expected
