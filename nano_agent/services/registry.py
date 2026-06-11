from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from nano_agent.config import AgentConfig

if TYPE_CHECKING:
    from nano_agent.services.llm import LLMClient
else:
    LLMClient = Any

LLMProviderFactory = Callable[[AgentConfig, str], LLMClient]
_LLM_PROVIDERS: dict[str, LLMProviderFactory] = {}


def register_llm_provider(name: str, factory: LLMProviderFactory) -> None:
    """注册 LLM provider 工厂，避免 agent.py 硬编码 provider 分支。"""
    _LLM_PROVIDERS[name] = factory


def create_llm_client(config: AgentConfig, repo_url: str) -> LLMClient:
    """按配置创建 LLM 客户端。"""
    _import_builtin_providers()
    if config.llm_provider not in _LLM_PROVIDERS:
        raise ValueError(f"Unsupported llm provider: {config.llm_provider}")
    return _LLM_PROVIDERS[config.llm_provider](config, repo_url)


def _import_builtin_providers() -> None:
    """导入内置 provider 模块，触发模块级注册。"""
    import nano_agent.services.llm  # noqa: F401
    import nano_agent.services.openai_compatible  # noqa: F401
