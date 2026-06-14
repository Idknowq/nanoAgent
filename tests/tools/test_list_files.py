from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.list_files import ListFilesTool


def make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=AgentConfig(workspace_root=tmp_path),
    )


def listed_paths(result) -> list[str]:  # type: ignore[no-untyped-def]
    return [entry["path"] for entry in result.data["entries"]]


def test_list_files_returns_stable_tree(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme", encoding="utf-8")

    result = ListFilesTool().invoke({"path": ".", "max_depth": 2}, make_context(tmp_path))

    assert result.success
    assert listed_paths(result) == ["README.md", "src", "src/app.py"]
    assert result.data["entries"][0]["size"] == 6
    assert not result.data["truncated"]


def test_list_files_normalizes_absolute_workspace_root(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("readme", encoding="utf-8")

    result = ListFilesTool().invoke({"path": str(tmp_path)}, make_context(tmp_path))

    assert result.success
    assert result.data["root"] == "."
    assert listed_paths(result) == ["README.md"]


def test_list_files_respects_depth_limit(tmp_path: Path) -> None:
    (tmp_path / "src" / "nested").mkdir(parents=True)
    (tmp_path / "src" / "nested" / "app.py").touch()

    result = ListFilesTool().invoke({"path": ".", "max_depth": 0}, make_context(tmp_path))

    assert listed_paths(result) == ["src"]


def test_list_files_ignores_hidden_and_dependency_directories(tmp_path: Path) -> None:
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").touch()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "visible.txt").touch()

    result = ListFilesTool().invoke({}, make_context(tmp_path))
    with_hidden = ListFilesTool().invoke({"include_hidden": True}, make_context(tmp_path))

    assert listed_paths(result) == ["visible.txt"]
    assert listed_paths(with_hidden) == [".hidden", "visible.txt"]


def test_list_files_does_not_follow_symlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-list-files"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "outside-link").symlink_to(outside, target_is_directory=True)

    result = ListFilesTool().invoke({}, make_context(tmp_path))

    assert listed_paths(result) == ["outside-link"]
    assert result.data["entries"][0]["type"] == "symlink"


def test_list_files_reports_truncation(tmp_path: Path) -> None:
    for index in range(5):
        (tmp_path / f"{index}.txt").touch()

    result = ListFilesTool().invoke({"max_entries": 2}, make_context(tmp_path))

    assert result.data["entry_count"] == 2
    assert result.data["truncated"]


def test_list_files_rejects_file_and_workspace_escape(tmp_path: Path) -> None:
    (tmp_path / "README.md").touch()

    file_result = ListFilesTool().invoke({"path": "README.md"}, make_context(tmp_path))
    escape_result = ListFilesTool().invoke({"path": ".."}, make_context(tmp_path))
    absolute_child_result = ListFilesTool().invoke(
        {"path": str(tmp_path / "nested")},
        make_context(tmp_path),
    )

    assert file_result.error_code == "invalid_input"
    assert escape_result.error_code == "invalid_input"
    assert absolute_child_result.error_code == "invalid_input"


def test_list_files_rejects_invalid_limits(tmp_path: Path) -> None:
    result = ListFilesTool().invoke({"max_depth": 11, "max_entries": 0}, make_context(tmp_path))

    assert result.error_code == "invalid_input"
