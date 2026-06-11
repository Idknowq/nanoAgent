import pytest

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.todo import TodoList, TodoStatus, TodoWriteTool


def test_todo_list_tracks_session_tasks() -> None:
    todos = TodoList()

    item = todos.add("Read repository files")
    todos.start(item.id, "Reading README.md")
    todos.complete(item.id, "README.md collected")

    assert todos.items[0].status == TodoStatus.COMPLETED
    assert todos.items[0].evidence == "README.md collected"


def test_todo_list_rejects_unknown_item() -> None:
    todos = TodoList()

    with pytest.raises(KeyError):
        todos.complete("missing")


def make_context(tmp_path):  # type: ignore[no-untyped-def]
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        config=AgentConfig(workspace_root=tmp_path),
    )


@pytest.mark.parametrize(
    ("input_data", "message"),
    [
        ({"action": "add", "title": ""}, "todo title is required"),
        ({"action": "complete"}, "todo id is required"),
        ({"action": "unknown"}, "Input should be"),
    ],
)
def test_todo_write_returns_invalid_input(tmp_path, input_data, message) -> None:  # type: ignore[no-untyped-def]
    result = TodoWriteTool().invoke(input_data, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "invalid_input"
    assert message in result.error_message


def test_todo_write_returns_invalid_input_for_unknown_item(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = TodoWriteTool().invoke(
        {"action": "complete", "id": "missing"},
        make_context(tmp_path),
    )

    assert not result.success
    assert result.error_code == "invalid_input"
    assert "Todo item not found" in result.error_message
