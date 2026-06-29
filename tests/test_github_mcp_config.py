import pytest

from nano_agent.mcp.github import (
    DEFAULT_GITHUB_MCP_DOCKER_IMAGE,
    DEFAULT_GITHUB_READ_ONLY,
    DEFAULT_GITHUB_TOOLSETS,
    GITHUB_MCP_DOCKER_IMAGE_ENV,
    GITHUB_READ_ONLY_ENV,
    GITHUB_TOKEN_ENV,
    GITHUB_TOOLSETS_ENV,
    build_github_mcp_stdio_config,
)


def test_github_mcp_stdio_config_uses_docker_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GITHUB_TOKEN_ENV, "secret-token")
    monkeypatch.setenv(GITHUB_TOOLSETS_ENV, "repos,issues")

    config = build_github_mcp_stdio_config(load_env=False)

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
        DEFAULT_GITHUB_MCP_DOCKER_IMAGE,
    )
    assert config.env == {
        GITHUB_TOOLSETS_ENV: "repos,issues",
        GITHUB_READ_ONLY_ENV: DEFAULT_GITHUB_READ_ONLY,
    }


def test_github_mcp_stdio_config_does_not_store_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GITHUB_TOKEN_ENV, "secret-token")

    config = build_github_mcp_stdio_config(load_env=False)

    assert "secret-token" not in repr(config)
    assert GITHUB_TOKEN_ENV not in config.env


def test_github_mcp_stdio_config_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GITHUB_TOKEN_ENV, raising=False)

    with pytest.raises(ValueError, match=GITHUB_TOKEN_ENV):
        build_github_mcp_stdio_config(load_env=False)


def test_github_mcp_stdio_config_reads_values_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(GITHUB_TOKEN_ENV, "secret-token")
    monkeypatch.setenv(GITHUB_MCP_DOCKER_IMAGE_ENV, "example/github-mcp-server")
    monkeypatch.setenv(GITHUB_TOOLSETS_ENV, "repos")
    monkeypatch.setenv(GITHUB_READ_ONLY_ENV, "0")

    config = build_github_mcp_stdio_config(load_env=False)

    assert config.args[-1] == "example/github-mcp-server"
    assert config.env[GITHUB_TOOLSETS_ENV] == "repos"
    assert config.env[GITHUB_READ_ONLY_ENV] == "0"


def test_github_mcp_stdio_config_uses_default_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(GITHUB_TOKEN_ENV, "secret-token")
    monkeypatch.delenv(GITHUB_MCP_DOCKER_IMAGE_ENV, raising=False)
    monkeypatch.delenv(GITHUB_TOOLSETS_ENV, raising=False)
    monkeypatch.delenv(GITHUB_READ_ONLY_ENV, raising=False)

    config = build_github_mcp_stdio_config(load_env=False)

    assert config.args[-1] == DEFAULT_GITHUB_MCP_DOCKER_IMAGE
    assert config.env[GITHUB_TOOLSETS_ENV] == DEFAULT_GITHUB_TOOLSETS
    assert config.env[GITHUB_READ_ONLY_ENV] == DEFAULT_GITHUB_READ_ONLY
