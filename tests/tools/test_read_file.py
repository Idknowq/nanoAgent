from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.read_file import ReadFileTool


def make_context(tmp_path: Path, *, max_file_bytes: int = 128_000) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        config=AgentConfig(workspace_root=tmp_path, max_file_bytes=max_file_bytes),
    )


def test_read_file_reads_utf8_text(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\nworld\n", encoding="utf-8")

    result = ReadFileTool().invoke({"path": "README.md"}, make_context(tmp_path))

    assert result.success
    assert result.data["content"] == "hello\nworld\n"
    assert result.data["path"] == "README.md"
    assert not result.data["truncated"]


def test_read_file_supports_byte_offset_and_limit(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_bytes(b"0123456789")

    result = ReadFileTool().invoke(
        {"path": "data.txt", "offset": 3, "limit": 4},
        make_context(tmp_path),
    )

    assert result.data["content"] == "3456"
    assert result.data["next_offset"] == 7
    assert result.data["truncated"]


def test_read_file_caps_limit_at_configured_maximum(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_bytes(b"abcdefgh")

    result = ReadFileTool().invoke(
        {"path": "data.txt", "limit": 100},
        make_context(tmp_path, max_file_bytes=4),
    )

    assert result.data["content"] == "abcd"
    assert result.data["bytes_read"] == 4
    assert result.data["truncated"]


def test_read_file_handles_empty_file(tmp_path: Path) -> None:
    (tmp_path / "empty.txt").touch()

    result = ReadFileTool().invoke({"path": "empty.txt"}, make_context(tmp_path))

    assert result.success
    assert result.data["content"] == ""
    assert result.data["bytes_read"] == 0


def test_read_file_rejects_missing_file_and_directory(tmp_path: Path) -> None:
    missing = ReadFileTool().invoke({"path": "missing.txt"}, make_context(tmp_path))
    directory = ReadFileTool().invoke({"path": "."}, make_context(tmp_path))

    assert missing.error_code == "invalid_input"
    assert directory.error_code == "invalid_input"


def test_read_file_rejects_binary_file(tmp_path: Path) -> None:
    (tmp_path / "binary.dat").write_bytes(b"text\x00binary")

    result = ReadFileTool().invoke({"path": "binary.dat"}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "invalid_input"
    assert "binary" in result.error_message


def test_read_file_rejects_workspace_escape(tmp_path: Path) -> None:
    result = ReadFileTool().invoke({"path": "../secret.txt"}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "invalid_input"
    assert "escapes" in result.error_message


def test_read_file_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-read-file"
    outside.mkdir(exist_ok=True)
    secret = outside / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (tmp_path / "secret-link").symlink_to(secret)

    result = ReadFileTool().invoke({"path": "secret-link"}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "invalid_input"
