from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class MCPTransportType(StrEnum):
    """Supported MCP transport families."""

    STDIO = "stdio"
    HTTP = "http"


class MCPServerConfig(BaseModel):
    """Configuration for one external MCP server."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(pattern=_SERVER_NAME_RE.pattern)  # Tool namespace for this server.
    transport: MCPTransportType  # Transport used to connect to the server.
    command: str | None = None  # Executable used by stdio servers.
    args: tuple[str, ...] = ()  # Arguments passed to stdio server commands.
    env: dict[str, str] = Field(default_factory=dict)  # Environment overrides for local servers.
    url: str | None = None  # HTTP endpoint for remote servers.
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP headers for remote servers.
    enabled: bool = True  # Whether this server should be considered for startup.

    @model_validator(mode="after")
    def validate_transport_fields(self) -> MCPServerConfig:
        """Validate the mutually exclusive fields required by each transport."""
        if self.transport is MCPTransportType.STDIO:
            if not self.command:
                raise ValueError("stdio MCP server requires command")
            if self.url is not None:
                raise ValueError("stdio MCP server does not accept url")
        if self.transport is MCPTransportType.HTTP:
            if not self.url:
                raise ValueError("http MCP server requires url")
            if self.command is not None:
                raise ValueError("http MCP server does not accept command")
        return self


class MCPInitializeResult(BaseModel):
    """Result of the MCP initialize handshake."""

    protocol_version: str  # Negotiated MCP protocol version.
    capabilities: dict[str, Any] = Field(default_factory=dict)  # Server capabilities.
    server_info: dict[str, Any] = Field(default_factory=dict)  # Server identity metadata.
    raw: dict[str, Any] = Field(default_factory=dict)  # Original initialize result.


class MCPToolDefinition(BaseModel):
    """Tool metadata discovered from one MCP server."""

    model_config = ConfigDict(extra="forbid")

    server_name: str = Field(pattern=_SERVER_NAME_RE.pattern)  # MCP server namespace.
    remote_name: str = Field(pattern=_TOOL_NAME_RE.pattern)  # Tool name exposed by the server.
    tool_name: str  # LLM-safe namespaced tool name exposed to nanoAgent.
    description: str = ""  # Tool description supplied by the MCP server.
    input_schema: dict[str, Any] = Field(default_factory=dict)  # JSON schema for tool input.

    @model_validator(mode="after")
    def validate_namespaced_tool_name(self) -> MCPToolDefinition:
        """Ensure the local tool name is derived from server and remote names."""
        expected = f"{self.server_name}__{self.remote_name}"
        if self.tool_name != expected:
            raise ValueError(f"MCP tool name must be {expected}")
        return self


class MCPToolCallResult(BaseModel):
    """Result returned from an MCP tools/call request."""

    content: list[dict[str, Any]] = Field(default_factory=list)  # MCP content blocks.
    is_error: bool = False  # Whether the MCP server marked the tool result as an error.
    raw: dict[str, Any] = Field(default_factory=dict)  # Original tools/call result.
