from __future__ import annotations

import os

from dotenv import load_dotenv

from nano_agent.mcp.models import MCPServerConfig


GITHUB_MCP_DOCKER_IMAGE_ENV = "GITHUB_MCP_DOCKER_IMAGE"
GITHUB_TOKEN_ENV = "GITHUB_PERSONAL_ACCESS_TOKEN"
GITHUB_TOOLSETS_ENV = "GITHUB_TOOLSETS"
GITHUB_READ_ONLY_ENV = "GITHUB_READ_ONLY"
DEFAULT_GITHUB_MCP_DOCKER_IMAGE = "ghcr.io/github/github-mcp-server"
DEFAULT_GITHUB_TOOLSETS = "context,repos,issues,pull_requests"
DEFAULT_GITHUB_READ_ONLY = "1"


def build_github_mcp_stdio_config(
    *,
    token_env: str = GITHUB_TOKEN_ENV,
    load_env: bool = True,
) -> MCPServerConfig:
    """Build a stdio MCP config for the official GitHub MCP Docker image."""
    if load_env:
        load_dotenv()
    if not os.environ.get(token_env):
        raise ValueError(f"{token_env} is required for GitHub MCP stdio config")

    image = os.environ.get(GITHUB_MCP_DOCKER_IMAGE_ENV, DEFAULT_GITHUB_MCP_DOCKER_IMAGE)
    toolsets = os.environ.get(GITHUB_TOOLSETS_ENV, DEFAULT_GITHUB_TOOLSETS)
    read_only = os.environ.get(GITHUB_READ_ONLY_ENV, DEFAULT_GITHUB_READ_ONLY)
    env = {
        GITHUB_TOOLSETS_ENV: toolsets,
        GITHUB_READ_ONLY_ENV: read_only,
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
        image,
    )
    return MCPServerConfig(
        name="github",
        transport="stdio",
        command="docker",
        args=args,
        env=env,
    )
