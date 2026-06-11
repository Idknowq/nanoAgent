from __future__ import annotations

import shlex
from typing import Protocol

from nano_agent.config import AgentConfig
from nano_agent.models import AgentMessage, LLMResponse, ToolUseRequest
from nano_agent.services.registry import register_llm_provider
from nano_agent.tools.base import ToolSpec


class LLMClient(Protocol):
    """模型服务协议，负责在 Agent loop 中基于消息历史选择文本或工具调用。"""

    def complete(self, messages: list[AgentMessage], tools: list[ToolSpec]) -> LLMResponse: # type: ignore
        """返回一轮 LLM 响应。"""


class ScriptedMvpLLMClient:
    """未接入真实模型前的确定性脚本客户端，用于验证 Agent loop。"""

    def __init__(self, repo_url: str) -> None:
        self.repo_url = repo_url  # 保存用户输入的目标仓库地址。
        self._step = 0  # 记录脚本执行到第几轮，模拟 LLM 多轮 tool_use。

    def complete(self, messages: list[AgentMessage], tools: list[ToolSpec]) -> LLMResponse:
        self._step += 1
        repo = shlex.quote(self.repo_url)

        if self._step == 1:
            return LLMResponse(
                content="I will clone the repository with bash.",
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="toolu_clone",
                        name="bash",
                        input={"command": f"git clone {repo} ."},
                    )
                ],
            )

        if self._step == 2:
            command = (
                "printf 'PWD\\n' && pwd && "
                "printf '\\nKEY_FILES\\n' && "
                "find . -maxdepth 2 "
                "\\( -name README.md -o -name pyproject.toml -o -name package.json "
                "-o -name requirements.txt \\) -print | sort"
            )
            return LLMResponse(
                content="I will inspect key repository files.",
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(id="toolu_inspect", name="bash", input={"command": command})
                ],
            )

        return LLMResponse(
            content="end_turn: repository clone and initial inspection tool calls completed.",
            stop_reason="end_turn",
        )


class StubLLMClient:
    """未配置真实模型时的空响应客户端。"""

    def complete(self, messages: list[AgentMessage], tools: list[ToolSpec]) -> LLMResponse:
        return LLMResponse(content="end_turn: LLM integration is not configured.", stop_reason="end_turn")


def _build_scripted_client(config: AgentConfig, repo_url: str) -> ScriptedMvpLLMClient:
    return ScriptedMvpLLMClient(repo_url=repo_url)


register_llm_provider("scripted", _build_scripted_client)
