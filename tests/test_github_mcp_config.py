import pytest

from nano_agent.mcp.github import (
    GITHUB_MCP_DOCKER_IMAGE,
    GITHUB_READ_ONLY_ENV,
    GITHUB_TOKEN_ENV,
    GITHUB_TOOLSETS_ENV,
    build_github_mcp_stdio_config,
)


def test_github_mcp_stdio_config_uses_docker_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GITHUB_TOKEN_ENV, "secret-token")

    config = build_github_mcp_stdio_config(toolsets="repos,issues")

    assert config.name == "github"
    assert config.transport == "stdio"
    assert config.command == "docker"
    assert config.args == (
        "run",
        "-i",
        "--rm",
        "-e",
        GITHUB_TOKEN_ENV,
        "-e",
        GITHUB_TOOLSETS_ENV,
        "-e",
        GITHUB_READ_ONLY_ENV,
        GITHUB_MCP_DOCKER_IMAGE,
    )
    assert config.env == {
        GITHUB_TOOLSETS_ENV: "repos,issues",
        GITHUB_READ_ONLY_ENV: "1",
    }


def test_github_mcp_stdio_config_does_not_store_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GITHUB_TOKEN_ENV, "secret-token")

    config = build_github_mcp_stdio_config()

    assert "secret-token" not in repr(config)
    assert GITHUB_TOKEN_ENV not in config.env


def test_github_mcp_stdio_config_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GITHUB_TOKEN_ENV, raising=False)

    with pytest.raises(ValueError, match=GITHUB_TOKEN_ENV):
        build_github_mcp_stdio_config()


def test_github_mcp_stdio_config_can_disable_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(GITHUB_TOKEN_ENV, "secret-token")

    config = build_github_mcp_stdio_config(read_only=False)

    assert config.env[GITHUB_READ_ONLY_ENV] == "0"
