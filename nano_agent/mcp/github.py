from __future__ import annotations

import os

from nano_agent.mcp.models import MCPServerConfig


GITHUB_MCP_DOCKER_IMAGE = "ghcr.io/github/github-mcp-server"
GITHUB_TOKEN_ENV = "GITHUB_PERSONAL_ACCESS_TOKEN"
GITHUB_TOOLSETS_ENV = "GITHUB_TOOLSETS"
GITHUB_READ_ONLY_ENV = "GITHUB_READ_ONLY"


def build_github_mcp_stdio_config(
    *,
    token_env: str = GITHUB_TOKEN_ENV,
    toolsets: str = "context,repos,issues,pull_requests",
    read_only: bool = True,
) -> MCPServerConfig:
    """Build a stdio MCP config for the official GitHub MCP Docker image."""
    if not os.environ.get(token_env):
        raise ValueError(f"{token_env} is required for GitHub MCP stdio config")

    env = {
        GITHUB_TOOLSETS_ENV: toolsets,
        GITHUB_READ_ONLY_ENV: "1" if read_only else "0",
    }
    args = (
        "run",
        "-i",
        "--rm",
        "-e",
        token_env,
        "-e",
        GITHUB_TOOLSETS_ENV,
        "-e",
        GITHUB_READ_ONLY_ENV,
        GITHUB_MCP_DOCKER_IMAGE,
    )
    return MCPServerConfig(
        name="github",
        transport="stdio",
        command="docker",
        args=args,
        env=env,
    )
