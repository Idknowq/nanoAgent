from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from nano_agent.config import AgentConfig
from nano_agent.models import (
    AgentMessage,
    LLMResponse,
    LLMStopReason,
    LLMUsage,
    ToolUseRequest,
)
from nano_agent.services.errors import LLMErrorKind, LLMServiceError, normalize_llm_error
from nano_agent.services.registry import register_llm_provider
from nano_agent.tools.base import ToolSpec


class OpenAICompatibleLLMClient:
    """OpenAI API 格式的 LLM 客户端，用于 DeepSeek 等兼容服务。"""

    def __init__(self, client: OpenAI, model: str, provider: str = "openai_compatible") -> None:
        self.client = client  # 保存 OpenAI-compatible SDK 客户端。
        self.model = model  # 保存当前调用的模型名。
        self.provider = provider

    @classmethod
    def from_deepseek_env(cls, model: str | None = None) -> OpenAICompatibleLLMClient:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_name = model or os.getenv("DEEPSEEK_MODEL", "deepseek-pro")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set in environment or .env")
        return cls(
            client=OpenAI(api_key=api_key, base_url=base_url),
            model=model_name,
            provider="deepseek",
        )

    def complete(self, messages: list[AgentMessage], tools: list[ToolSpec]) -> LLMResponse:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self._to_openai_messages(messages),  # type: ignore
                tools=self._to_openai_tools(tools),  # type: ignore
            )
        except Exception as exc:
            raise normalize_llm_error(exc) from exc

        if not response.choices:
            raise LLMServiceError(
                "provider response did not contain any choices",
                kind=LLMErrorKind.INVALID_RESPONSE,
            )
        choice = response.choices[0]
        message = choice.message
        provider_stop_reason = str(getattr(choice, "finish_reason", "") or "")
        stop_reason = self._normalize_stop_reason(provider_stop_reason)
        tool_uses, truncated_tool_call = self._parse_tool_calls(
            message.tool_calls or [],
            stop_reason=stop_reason,
        )
        if tool_uses and stop_reason not in {
            LLMStopReason.MAX_TOKENS,
            LLMStopReason.CONTENT_FILTER,
        }:
            stop_reason = LLMStopReason.TOOL_USE
        usage = getattr(response, "usage", None)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        return LLMResponse(
            content=message.content or "",
            tool_uses=tool_uses,
            stop_reason=stop_reason,
            provider_stop_reason=provider_stop_reason or None,
            truncated_tool_call=truncated_tool_call,
            provider=self.provider,
            model=getattr(response, "model", None) or self.model,
            usage=LLMUsage(
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
                cached_tokens=getattr(prompt_details, "cached_tokens", None),
            )
            if usage is not None
            else None,
        )

    @staticmethod
    def _normalize_stop_reason(provider_reason: str) -> LLMStopReason:
        return {
            "tool_calls": LLMStopReason.TOOL_USE,
            "function_call": LLMStopReason.TOOL_USE,
            "stop": LLMStopReason.END_TURN,
            "length": LLMStopReason.MAX_TOKENS,
            "max_tokens": LLMStopReason.MAX_TOKENS,
            "content_filter": LLMStopReason.CONTENT_FILTER,
        }.get(provider_reason.lower(), LLMStopReason.UNKNOWN)

    @staticmethod
    def _parse_tool_calls(
        tool_calls: list[Any],
        *,
        stop_reason: LLMStopReason,
    ) -> tuple[list[ToolUseRequest], bool]:
        parsed: list[ToolUseRequest] = []
        for tool_call in tool_calls:
            try:
                input_data = json.loads(tool_call.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError) as exc:
                if stop_reason == LLMStopReason.MAX_TOKENS:
                    return [], True
                raise LLMServiceError(
                    "provider returned invalid tool call arguments",
                    kind=LLMErrorKind.INVALID_RESPONSE,
                ) from exc
            if not isinstance(input_data, dict):
                raise LLMServiceError(
                    "provider tool call arguments must decode to an object",
                    kind=LLMErrorKind.INVALID_RESPONSE,
                )
            parsed.append(
                ToolUseRequest(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    input=input_data,
                )
            )
        return parsed, False

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
