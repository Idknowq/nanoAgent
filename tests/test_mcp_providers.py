import pytest

from nano_agent.mcp.github import GITHUB_TOKEN_ENV
from nano_agent.mcp.providers import (
    build_mcp_provider_config,
    build_mcp_provider_configs,
    registered_mcp_providers,
)


def test_registered_mcp_providers_includes_github() -> None:
    """Provider registry exposes the built-in GitHub provider."""
    assert "github" in registered_mcp_providers()


def test_build_mcp_provider_config_builds_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """GitHub provider resolves to the GitHub MCP server config builder."""
    monkeypatch.setenv(GITHUB_TOKEN_ENV, "secret-token")

    config = build_mcp_provider_config("github")

    assert config.name == "github"
    assert config.command == "docker"


def test_build_mcp_provider_configs_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multiple provider names are expanded in user-specified order."""
    monkeypatch.setenv(GITHUB_TOKEN_ENV, "secret-token")

    configs = build_mcp_provider_configs(("github",))

    assert [config.name for config in configs] == ["github"]


def test_build_mcp_provider_config_rejects_unknown_provider() -> None:
    """Unknown provider names fail before agent runtime startup."""
    with pytest.raises(ValueError, match="Unknown MCP provider: missing"):
        build_mcp_provider_config("missing")
