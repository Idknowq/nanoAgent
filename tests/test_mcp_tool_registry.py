from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nano_agent.mcp import (
    MCPClientSession,
    MCPServerConfig,
    MCPToolDefinition,
    StdioMCPTransport,
)
from nano_agent.mcp.registry import build_mcp_tool_registry
from nano_agent.models import ApprovalLevel


def make_session(tmp_path: Path) -> MCPClientSession:
    server_script = tmp_path / "unused_mcp_server.py"
    server_script.write_text("import sys\nfor line in sys.stdin:\n    pass", encoding="utf-8")
    server = MCPServerConfig(
        name="github",
        transport="stdio",
        command=sys.executable,
        args=(str(server_script),),
    )
    return MCPClientSession(server=server, transport=StdioMCPTransport(server))


def make_definition(
    remote_name: str,
    *,
    description: str = "Search issues.",
) -> MCPToolDefinition:
    return MCPToolDefinition(
        server_name="github",
        remote_name=remote_name,
        tool_name=f"github.{remote_name}",
        description=description,
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )


def test_build_mcp_tool_registry_registers_namespaced_tools(tmp_path: Path) -> None:
    registry = build_mcp_tool_registry(
        make_session(tmp_path),
        [make_definition("search_issues")],
    )

    assert registry.contains("github.search_issues")
    assert registry.get("github.search_issues").name == "github.search_issues"


def test_build_mcp_tool_registry_rejects_duplicate_tool_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="already registered"):
        build_mcp_tool_registry(
            make_session(tmp_path),
            [
                make_definition("search_issues"),
                make_definition("search_issues"),
            ],
        )


def test_mcp_tool_registry_specs_include_adapter_metadata(tmp_path: Path) -> None:
    registry = build_mcp_tool_registry(
        make_session(tmp_path),
        [make_definition("search_issues")],
    )

    spec = registry.specs()[0]
    assert spec.name == "github.search_issues"
    assert spec.description == "Search issues."
    assert spec.approval_level is ApprovalLevel.READ
    assert spec.input_schema == {"type": "object", "properties": {"query": {"type": "string"}}}
    assert spec.category == "mcp"
    assert spec.enabled
    assert not spec.requires_workspace
    assert not spec.is_mutating
    assert spec.can_run_concurrently
    assert spec.conflict_group == "mcp:github"
    assert not spec.requires_exclusive_execution


def test_mcp_tool_registry_selected_preserves_mcp_tool(tmp_path: Path) -> None:
    registry = build_mcp_tool_registry(
        make_session(tmp_path),
        [
            make_definition("search_issues"),
            make_definition("get_pull_request", description="Get pull request."),
        ],
    )

    selected = registry.selected({"github.get_pull_request"})

    assert selected.names() == {"github.get_pull_request"}
    assert selected.get("github.get_pull_request").description == "Get pull request."
