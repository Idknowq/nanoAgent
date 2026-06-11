import pytest

from nano_agent.config import AgentConfig
from nano_agent.services.llm import ScriptedMvpLLMClient
from nano_agent.services.registry import create_llm_client


def test_deepseek_is_the_default_provider() -> None:
    assert AgentConfig().llm_provider == "deepseek"


def test_scripted_client_remains_available_for_direct_test_injection() -> None:
    client = ScriptedMvpLLMClient("https://example.com/repo.git")

    assert client.repo_url == "https://example.com/repo.git"


def test_scripted_is_not_registered_as_a_production_provider() -> None:
    config = AgentConfig(llm_provider="scripted")

    with pytest.raises(ValueError, match="Unsupported llm provider"):
        create_llm_client(config, "https://example.com/repo.git")
