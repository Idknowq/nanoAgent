from __future__ import annotations

from typing import Protocol

from nano_agent.models import AgentMessage, LLMResponse, ToolUseRequest
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

        if self._step == 1:
            return LLMResponse(
                content="I will clone the repository.",
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="toolu_clone",
                        name="clone_repo",
                        input={"repo_url": self.repo_url, "depth": 1},
                    )
                ],
            )

        if self._step == 2:
            return LLMResponse(
                content="I will inspect key repository files.",
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="toolu_inspect",
                        name="list_files",
                        input={"path": ".", "max_depth": 2, "max_entries": 500},
                    )
                ],
            )

        return LLMResponse(
            content="I will submit the structured result.",
            stop_reason="tool_use",
            tool_uses=[
                ToolUseRequest(
                    id="toolu_finish",
                    name="finish_run",
                    input={
                        "status": "completed",
                        "problem": "Clone and initial repository inspection were requested.",
                        "root_cause": "No deeper diagnosis was included in the scripted MVP flow.",
                        "resolution": "Cloned the repository and listed its key files.",
                        "verification_summary": "list_files completed successfully.",
                        "remaining_risks": [
                            "The scripted client does not diagnose or repair repository defects."
                        ],
                    },
                )
            ],
        )
