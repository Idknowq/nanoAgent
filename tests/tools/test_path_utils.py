from pathlib import Path

import pytest

from nano_agent.tools.path_utils import (
    WorkspacePathError,
    resolve_workspace_path,
    workspace_relative_path,
)


async def test_resolve_workspace_path_normalizes_relative_path(tmp_path: Path) -> None:
    target = resolve_workspace_path(tmp_path, "src/../README.md")

    assert target == tmp_path / "README.md"
    assert workspace_relative_path(tmp_path, target) == "README.md"


async def test_resolve_workspace_path_rejects_empty_and_absolute_paths(tmp_path: Path) -> None:
    with pytest.raises(WorkspacePathError, match="empty"):
        resolve_workspace_path(tmp_path, "")

    with pytest.raises(WorkspacePathError, match="absolute"):
        resolve_workspace_path(tmp_path, str(tmp_path / "README.md"))


async def test_resolve_workspace_path_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(WorkspacePathError, match="escapes"):
        resolve_workspace_path(tmp_path, "../outside.txt")


async def test_resolve_workspace_path_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspacePathError, match="escapes"):
        resolve_workspace_path(tmp_path, "link/secret.txt")


async def test_resolve_workspace_path_can_require_existing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_workspace_path(tmp_path, "missing.txt", must_exist=True)


async def test_resolve_workspace_path_can_reject_workspace_root(tmp_path: Path) -> None:
    assert resolve_workspace_path(tmp_path, ".") == tmp_path

    with pytest.raises(WorkspacePathError, match="root"):
        resolve_workspace_path(tmp_path, ".", allow_root=False)


async def test_resolve_workspace_path_rejects_non_directory_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.write_text("not a directory", encoding="utf-8")

    with pytest.raises(WorkspacePathError, match="not a directory"):
        resolve_workspace_path(workspace, "README.md")
