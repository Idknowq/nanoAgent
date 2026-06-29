from __future__ import annotations

from collections.abc import Callable

from nano_agent.mcp.github import build_github_mcp_stdio_config
from nano_agent.mcp.models import MCPServerConfig


MCPProviderBuilder = Callable[[], MCPServerConfig]

_PROVIDERS: dict[str, MCPProviderBuilder] = {
    "github": build_github_mcp_stdio_config,
}


def build_mcp_provider_config(name: str) -> MCPServerConfig:
    """Build an MCP server config from a registered provider name."""
    try:
        builder = _PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown MCP provider: {name}") from exc
    return builder()


def build_mcp_provider_configs(names: tuple[str, ...]) -> tuple[MCPServerConfig, ...]:
    """Build MCP server configs for registered provider names."""
    return tuple(build_mcp_provider_config(name) for name in names)


def registered_mcp_providers() -> tuple[str, ...]:
    """Return registered MCP provider names."""
    return tuple(_PROVIDERS)
