from types import SimpleNamespace

from openai import OpenAI

from nano_agent.models import AgentMessage
from nano_agent.services.openai_compatible import OpenAICompatibleLLMClient
from nano_agent.tools.base import ToolRegistry
from nano_agent.tools.todo import TodoWriteTool


class FakeCompletions:
    """测试用 completions 对象，记录请求并返回固定 tool_call。"""

    def __init__(self) -> None:
        self.last_request = None  # 保存最近一次 create 调用参数。

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_request = kwargs
        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="todo_write", arguments='{"action":"add","title":"Inspect"}'),
        )
        message = SimpleNamespace(content=None, tool_calls=[tool_call])
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class FakeOpenAI:
    """测试用 OpenAI-compatible client。"""

    def __init__(self) -> None:
        self.completions = FakeCompletions()  # 保存 fake completions 入口。
        self.chat = SimpleNamespace(completions=self.completions)


def test_openai_compatible_client_parses_tool_calls() -> None:
    fake = FakeOpenAI()
    client = OpenAICompatibleLLMClient(client=fake, model="deepseek-test")  # type: ignore[arg-type]
    tools = ToolRegistry([TodoWriteTool()]).specs()

    response = client.complete([AgentMessage(role="user", content="start")], tools)

    assert response.stop_reason == "tool_use"
    assert response.tool_uses[0].name == "todo_write"
    assert response.tool_uses[0].input["title"] == "Inspect"
    assert fake.completions.last_request["model"] == "deepseek-test"
    assert fake.completions.last_request["tools"][0]["function"]["parameters"]["required"] == ["action"]


def test_openai_message_conversion_preserves_assistant_tool_calls() -> None:
    client = OpenAICompatibleLLMClient(client=OpenAI(api_key="test"), model="test")
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
