from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from nano_agent.config import AgentConfig
from nano_agent.models import AgentMessage, LLMResponse, ToolUseRequest
from nano_agent.services.registry import register_llm_provider
from nano_agent.tools.base import ToolSpec


class OpenAICompatibleLLMClient:
    """OpenAI API 格式的 LLM 客户端，用于 DeepSeek 等兼容服务。"""

    def __init__(self, client: OpenAI, model: str) -> None:
        self.client = client  # 保存 OpenAI-compatible SDK 客户端。
        self.model = model  # 保存当前调用的模型名。

    @classmethod
    def from_deepseek_env(cls, model: str | None = None) -> OpenAICompatibleLLMClient:
        load_dotenv()
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set in environment or .env")
        return cls(client=OpenAI(api_key=api_key, base_url=base_url), model=model_name)

    def complete(self, messages: list[AgentMessage], tools: list[ToolSpec]) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self._to_openai_messages(messages), # type: ignore
            tools=self._to_openai_tools(tools), # type: ignore
        )
        message = response.choices[0].message
        tool_uses = [
            ToolUseRequest(
                id=tool_call.id,
                name=tool_call.function.name, # type: ignore
                input=json.loads(tool_call.function.arguments or "{}"), # type: ignore
            )
            for tool_call in message.tool_calls or []
        ]
        return LLMResponse(
            content=message.content or "",
            tool_uses=tool_uses,
            stop_reason="tool_use" if tool_uses else "end_turn",
        )

    def _to_openai_messages(self, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
                continue

            item: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.role == "assistant" and message.tool_uses:
                item["tool_calls"] = [
                    {
                        "id": tool_use.id,
                        "type": "function",
                        "function": {
                            "name": tool_use.name,
                            "arguments": json.dumps(tool_use.input, ensure_ascii=False),
                        },
                    }
                    for tool_use in message.tool_uses
                ]
            converted.append(item)
        return converted

    def _to_openai_tools(self, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]


def _build_deepseek_client(config: AgentConfig, repo_url: str) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient.from_deepseek_env(model=config.llm_model)


register_llm_provider("deepseek", _build_deepseek_client)
