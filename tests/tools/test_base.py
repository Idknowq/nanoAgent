from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.tools.base import RuntimeTool, ToolContext, ToolInput, ToolRegistry, ToolResult
from nano_agent.tools.errors import ToolInputError


class ExampleInput(ToolInput):
    value: int


class ExampleTool(RuntimeTool):
    name = "example"
    description = "Example tool."
    input_model = ExampleInput

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        if input_data["value"] < 0:
            raise ToolInputError("value must be non-negative")
        return ToolResult(success=True, summary="ok", data=input_data)


class BrokenTool(RuntimeTool):
    name = "broken"
    description = "Broken tool."

    def run(self, input_data: dict, context: ToolContext) -> ToolResult:
        raise RuntimeError("programming defect")


def make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=AgentConfig(workspace_root=tmp_path),
    )


def test_runtime_tool_validates_input(tmp_path: Path) -> None:
    result = ExampleTool().invoke({"value": "3"}, make_context(tmp_path))

    assert result.success
    assert result.data["value"] == 3


def test_runtime_tool_returns_validation_failure(tmp_path: Path) -> None:
    result = ExampleTool().invoke({"value": "invalid"}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "invalid_input"


def test_runtime_tool_returns_expected_tool_failure(tmp_path: Path) -> None:
    result = ExampleTool().invoke({"value": -1}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "invalid_input"
    assert result.error_message == "value must be non-negative"


def test_runtime_tool_does_not_hide_programming_errors(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="programming defect"):
        BrokenTool().invoke({}, make_context(tmp_path))


def test_tool_registry_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="already registered"):
        ToolRegistry([ExampleTool(), ExampleTool()])
