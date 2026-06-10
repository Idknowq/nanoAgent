import pytest

from nano_agent.tools.todo import TodoList, TodoStatus


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
