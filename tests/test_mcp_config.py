from pydantic import ValidationError

import pytest

from nano_agent.config import AgentConfig
from nano_agent.mcp import MCPServerConfig, MCPTransportType


def test_agent_config_has_no_mcp_servers_by_default() -> None:
    config = AgentConfig()

    assert config.mcp_servers == ()


def test_agent_config_accepts_mcp_servers() -> None:
    server = MCPServerConfig(
        name="github",
        transport=MCPTransportType.STDIO,
        command="github-mcp-server",
        args=("stdio",),
    )
    config = AgentConfig(mcp_servers=(server,))

    assert config.mcp_servers == (server,)


def test_stdio_server_accepts_command_and_args() -> None:
    server = MCPServerConfig(
        name="github",
        transport="stdio",
        command="github-mcp-server",
        args=("stdio",),
    )

    assert server.transport is MCPTransportType.STDIO
    assert server.command == "github-mcp-server"
    assert server.args == ("stdio",)


def test_stdio_server_requires_command() -> None:
    with pytest.raises(ValidationError, match="stdio MCP server requires command"):
        MCPServerConfig(name="github", transport="stdio")


def test_stdio_server_rejects_url() -> None:
    with pytest.raises(ValidationError, match="stdio MCP server does not accept url"):
        MCPServerConfig(
            name="github",
            transport="stdio",
            command="github-mcp-server",
            url="https://api.githubcopilot.com/mcp/",
        )


def test_http_server_accepts_url() -> None:
    server = MCPServerConfig(
        name="github",
        transport="http",
        url="https://api.githubcopilot.com/mcp/",
    )

    assert server.transport is MCPTransportType.HTTP
    assert server.url == "https://api.githubcopilot.com/mcp/"


def test_http_server_requires_url() -> None:
    with pytest.raises(ValidationError, match="http MCP server requires url"):
        MCPServerConfig(name="github", transport="http")


def test_http_server_rejects_command() -> None:
    with pytest.raises(ValidationError, match="http MCP server does not accept command"):
        MCPServerConfig(
            name="github",
            transport="http",
            command="github-mcp-server",
            url="https://api.githubcopilot.com/mcp/",
        )


@pytest.mark.parametrize("name", ["github.search", "github/mcp", ""])
def test_server_name_must_be_namespace_safe(name: str) -> None:
    with pytest.raises(ValidationError):
        MCPServerConfig(
            name=name,
            transport="stdio",
            command="github-mcp-server",
        )
