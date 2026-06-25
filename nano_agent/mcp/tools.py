"""Bridge MCP tools into nanoAgent RuntimeTool instances."""

from __future__ import annotations

from typing import Any, ClassVar

from nano_agent.mcp.client import MCPClient
from nano_agent.mcp.protocol import MCPTool
from nano_agent.models import ApprovalLevel
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolResult


class MCPToolAdapter(RuntimeTool):
    """Wraps a single MCP tool as a nanoAgent RuntimeTool.

    Each adapter holds a reference to the MCPClient so tool calls are
    forwarded to the MCP server at invocation time.
    """

    name: ClassVar[str]  # set per instance below
    description: ClassVar[str]
    approval_level: ClassVar[ApprovalLevel] = ApprovalLevel.EXECUTE_SAFE
    input_model: ClassVar[None] = None  # accept raw dict, server validates

    def __init__(self, mcp_tool: MCPTool, client: MCPClient) -> None:
        self._mcp_tool = mcp_tool
        self._client = client
        # Set class vars per instance (name/description must be static for registry)
        self.name = mcp_tool.name  # type: ignore[assignment]
        self.description = mcp_tool.description  # type: ignore[assignment]

    def run(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            result = self._client.call_tool(self.name, input_data)
        except Exception as exc:
            return ToolResult.failure(
                code="mcp_tool_error",
                message=f"MCP tool '{self.name}' failed: {exc}",
            )
        if result.is_error:
            error_text = ""
            for c in result.content:
                if isinstance(c, dict) and c.get("type") == "text":
                    error_text += str(c.get("text", ""))
            return ToolResult.failure(
                code="mcp_tool_returned_error",
                message=error_text or f"MCP tool '{self.name}' returned an error",
            )
        # Extract text content for the summary
        text_parts: list[str] = []
        data_parts: list[dict[str, Any]] = []
        for c in result.content:
            if isinstance(c, dict):
                if c.get("type") == "text":
                    text_parts.append(str(c.get("text", "")))
                else:
                    data_parts.append(c)
        summary = " ".join(text_parts)[:200] if text_parts else f"{self.name} completed"
        return ToolResult(
            success=True,
            summary=summary,
            data={"content": result.content},
        )


def discover_and_register(
    client: MCPClient,
    registry: Any,  # ToolRegistry to avoid circular import
) -> list[MCPToolAdapter]:
    """Discover tools from an MCP server and register them in the ToolRegistry.

    Returns the list of created adapters.
    """
    mcp_tools = client.list_tools()
    adapters = []
    for tool in mcp_tools:
        adapter = MCPToolAdapter(tool, client)
        registry.register(adapter)
        adapters.append(adapter)
    return adapters
