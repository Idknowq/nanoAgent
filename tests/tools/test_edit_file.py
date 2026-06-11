import os
import stat
from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.edit_file import EditFileTool


def make_context(tmp_path: Path, *, max_file_bytes: int = 128_000) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=AgentConfig(workspace_root=tmp_path, max_file_bytes=max_file_bytes),
    )


def test_edit_file_replaces_exact_text(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("value = 1\n", encoding="utf-8")

    result = EditFileTool().invoke(
        {"path": "app.py", "old_text": "value = 1", "new_text": "value = 2"},
        make_context(tmp_path),
    )

    assert result.success
    assert target.read_text(encoding="utf-8") == "value = 2\n"
    assert result.data == {
        "path": "app.py",
        "replacements": 1,
        "bytes_before": 10,
        "bytes_after": 10,
    }


def test_edit_file_supports_expected_multiple_replacements(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("old old old", encoding="utf-8")

    result = EditFileTool().invoke(
        {
            "path": "data.txt",
            "old_text": "old",
            "new_text": "new",
            "expected_replacements": 3,
        },
        make_context(tmp_path),
    )

    assert result.success
    assert target.read_text(encoding="utf-8") == "new new new"


@pytest.mark.parametrize(
    ("content", "expected", "message"),
    [
        ("value = 1", 1, "found 0"),
        ("old old", 1, "found 2"),
    ],
)
def test_edit_file_rejects_match_count_mismatch(
    tmp_path: Path,
    content: str,
    expected: int,
    message: str,
) -> None:
    target = tmp_path / "data.txt"
    target.write_text(content, encoding="utf-8")

    result = EditFileTool().invoke(
        {
            "path": "data.txt",
            "old_text": "old",
            "new_text": "new",
            "expected_replacements": expected,
        },
        make_context(tmp_path),
    )

    assert result.error_code == "invalid_input"
    assert message in result.error_message
    assert target.read_text(encoding="utf-8") == content


def test_edit_file_rejects_empty_old_text_and_noop(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("value", encoding="utf-8")

    empty = EditFileTool().invoke(
        {"path": "data.txt", "old_text": "", "new_text": "new"},
        make_context(tmp_path),
    )
    noop = EditFileTool().invoke(
        {"path": "data.txt", "old_text": "value", "new_text": "value"},
        make_context(tmp_path),
    )

    assert empty.error_code == "invalid_input"
    assert noop.error_code == "invalid_input"


def test_edit_file_preserves_whitespace_and_utf8(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("  旧值  \n", encoding="utf-8")

    result = EditFileTool().invoke(
        {"path": "data.txt", "old_text": "  旧值  ", "new_text": "  新值  "},
        make_context(tmp_path),
    )

    assert result.success
    assert target.read_text(encoding="utf-8") == "  新值  \n"


def test_edit_file_rejects_workspace_and_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-edit-file"
    outside.mkdir(exist_ok=True)
    secret = outside / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (tmp_path / "secret-link").symlink_to(secret)

    parent = EditFileTool().invoke(
        {"path": "../secret.txt", "old_text": "secret", "new_text": "changed"},
        make_context(tmp_path),
    )
    symlink = EditFileTool().invoke(
        {"path": "secret-link", "old_text": "secret", "new_text": "changed"},
        make_context(tmp_path),
    )

    assert parent.error_code == "invalid_input"
    assert symlink.error_code == "invalid_input"
    assert secret.read_text(encoding="utf-8") == "secret"


def test_edit_file_rejects_git_internal_path(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    config = git_dir / "config"
    config.write_text("secret", encoding="utf-8")

    result = EditFileTool().invoke(
        {"path": ".git/config", "old_text": "secret", "new_text": "changed"},
        make_context(tmp_path),
    )

    assert result.error_code == "invalid_input"
    assert ".git" in result.error_message
    assert config.read_text(encoding="utf-8") == "secret"


def test_edit_file_rejects_binary_and_large_files(tmp_path: Path) -> None:
    (tmp_path / "binary.dat").write_bytes(b"text\x00binary")
    (tmp_path / "large.txt").write_text("x" * 20, encoding="utf-8")
    context = make_context(tmp_path, max_file_bytes=10)

    binary = EditFileTool().invoke(
        {"path": "binary.dat", "old_text": "text", "new_text": "new"},
        context,
    )
    large = EditFileTool().invoke(
        {"path": "large.txt", "old_text": "x", "new_text": "y", "expected_replacements": 20},
        context,
    )

    assert binary.error_code == "invalid_input"
    assert large.error_code == "invalid_input"


def test_edit_file_rejects_update_larger_than_limit(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("small", encoding="utf-8")

    result = EditFileTool().invoke(
        {"path": "data.txt", "old_text": "small", "new_text": "x" * 20},
        make_context(tmp_path, max_file_bytes=10),
    )

    assert result.error_code == "invalid_input"
    assert target.read_text(encoding="utf-8") == "small"


def test_edit_file_preserves_permissions(tmp_path: Path) -> None:
    target = tmp_path / "script.py"
    target.write_text("print('old')\n", encoding="utf-8")
    os.chmod(target, 0o750)

    result = EditFileTool().invoke(
        {"path": "script.py", "old_text": "old", "new_text": "new"},
        make_context(tmp_path),
    )

    assert result.success
    assert stat.S_IMODE(target.stat().st_mode) == 0o750


def test_edit_file_atomic_failure_keeps_original(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "data.txt"
    target.write_text("old", encoding="utf-8")

    def fail_replace(source, destination):  # type: ignore[no-untyped-def]
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    result = EditFileTool().invoke(
        {"path": "data.txt", "old_text": "old", "new_text": "new"},
        make_context(tmp_path),
    )

    assert result.error_code == "execution_error"
    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".data.txt.*.tmp"))
