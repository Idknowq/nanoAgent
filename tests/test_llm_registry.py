import pytest

from nano_agent.config import AgentConfig
from nano_agent.services.llm import ScriptedMvpLLMClient
from nano_agent.services.registry import create_llm_client


async def test_deepseek_is_the_default_provider() -> None:
    config = AgentConfig()

    assert config.llm_provider == "deepseek"
    assert config.llm_model == "deepseek-v4-pro"
    assert config.llm_temperature == 0.0
    assert config.llm_max_output_tokens == 32_768
    assert not config.llm_thinking_enabled


async def test_scripted_client_remains_available_for_direct_test_injection() -> None:
    client = ScriptedMvpLLMClient("https://example.com/repo.git")

    assert client.repo_url == "https://example.com/repo.git"


async def test_scripted_is_not_registered_as_a_production_provider() -> None:
    config = AgentConfig(llm_provider="scripted")

    with pytest.raises(ValueError, match="Unsupported llm provider"):
        create_llm_client(config, "https://example.com/repo.git")
