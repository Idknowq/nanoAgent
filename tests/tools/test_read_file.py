import asyncio
import time
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.read_file import ReadFileTool


def make_context(tmp_path: Path, *, max_file_bytes: int = 128_000) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=AgentConfig(workspace_root=tmp_path, max_file_bytes=max_file_bytes),
    )


async def test_read_file_reads_utf8_text(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\nworld\n", encoding="utf-8")

    result = await ReadFileTool().invoke({"path": "README.md"}, make_context(tmp_path))

    assert result.success
    assert result.data["content"] == "hello\nworld\n"
    assert result.data["path"] == "README.md"
    assert not result.data["truncated"]


async def test_read_file_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    tool = ReadFileTool()
    original_read_bytes = tool._read_bytes

    def slow_read_bytes(*args, **kwargs):  # type: ignore[no-untyped-def]
        time.sleep(0.15)
        return original_read_bytes(*args, **kwargs)

    monkeypatch.setattr(tool, "_read_bytes", slow_read_bytes)
    started = time.monotonic()
    task = asyncio.create_task(tool.invoke({"path": "README.md"}, make_context(tmp_path)))
    await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    elapsed = time.monotonic() - started
    result = await task

    assert elapsed < 0.10
    assert result.success
    assert result.data["content"] == "hello\n"


async def test_read_file_supports_byte_offset_and_limit(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_bytes(b"0123456789")

    result = await ReadFileTool().invoke(
        {"path": "data.txt", "offset": 3, "limit": 4},
        make_context(tmp_path),
    )

    assert result.data["content"] == "3456"
    assert result.data["next_offset"] == 7
    assert result.data["truncated"]


async def test_read_file_supports_inclusive_line_range(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_text(
        "one\ntwo\nthree\nfour\n",
        encoding="utf-8",
    )

    result = await ReadFileTool().invoke(
        {"path": "data.txt", "line_start": 2, "line_end": 3},
        make_context(tmp_path),
    )

    assert result.success
    assert result.data["content"] == "two\nthree\n"
    assert result.data["line_start"] == 2
    assert result.data["line_end"] == 3
    assert result.data["next_line"] is None
    assert not result.data["truncated"]


async def test_read_file_line_range_is_bounded_by_configured_maximum(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = await ReadFileTool().invoke(
        {"path": "data.txt", "line_start": 1, "line_end": 3},
        make_context(tmp_path, max_file_bytes=6),
    )

    assert result.success
    assert result.data["content"] == "one\ntw"
    assert result.data["line_end"] == 1
    assert result.data["next_line"] == 2
    assert result.data["truncated"]


async def test_read_file_rejects_mixed_or_invalid_read_modes(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_text("one\ntwo\n", encoding="utf-8")
    context = make_context(tmp_path)

    mixed = await ReadFileTool().invoke(
        {"path": "data.txt", "offset": 0, "line_start": 1},
        context,
    )
    missing_start = await ReadFileTool().invoke(
        {"path": "data.txt", "line_end": 2},
        context,
    )
    reversed_range = await ReadFileTool().invoke(
        {"path": "data.txt", "line_start": 2, "line_end": 1},
        context,
    )

    assert mixed.error_code == "invalid_input"
    assert "mutually exclusive" in mixed.error_message
    assert missing_start.error_code == "invalid_input"
    assert "line_start is required" in missing_start.error_message
    assert reversed_range.error_code == "invalid_input"
    assert "line_end must be greater" in reversed_range.error_message


async def test_read_file_caps_limit_at_configured_maximum(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_bytes(b"abcdefgh")

    result = await ReadFileTool().invoke(
        {"path": "data.txt", "limit": 100},
        make_context(tmp_path, max_file_bytes=4),
    )

    assert result.data["content"] == "abcd"
    assert result.data["bytes_read"] == 4
    assert result.data["truncated"]


async def test_read_file_handles_empty_file(tmp_path: Path) -> None:
    (tmp_path / "empty.txt").touch()

    result = await ReadFileTool().invoke({"path": "empty.txt"}, make_context(tmp_path))

    assert result.success
    assert result.data["content"] == ""
    assert result.data["bytes_read"] == 0


async def test_read_file_rejects_missing_file_and_directory(tmp_path: Path) -> None:
    missing = await ReadFileTool().invoke({"path": "missing.txt"}, make_context(tmp_path))
    directory = await ReadFileTool().invoke({"path": "."}, make_context(tmp_path))

    assert missing.error_code == "invalid_input"
    assert directory.error_code == "invalid_input"


async def test_read_file_rejects_binary_file(tmp_path: Path) -> None:
    (tmp_path / "binary.dat").write_bytes(b"text\x00binary")

    result = await ReadFileTool().invoke({"path": "binary.dat"}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "invalid_input"
    assert "binary" in result.error_message


async def test_read_file_rejects_workspace_escape(tmp_path: Path) -> None:
    result = await ReadFileTool().invoke({"path": "../secret.txt"}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "invalid_input"
    assert "escapes" in result.error_message


async def test_read_file_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-read-file"
    outside.mkdir(exist_ok=True)
    secret = outside / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (tmp_path / "secret-link").symlink_to(secret)

    result = await ReadFileTool().invoke({"path": "secret-link"}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "invalid_input"
