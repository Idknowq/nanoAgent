from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.grep import GrepTool


def make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "runs" / "test",
        config=AgentConfig(workspace_root=tmp_path),
    )


async def test_grep_returns_line_context_and_byte_offset(tmp_path: Path) -> None:
    content = "alpha\nbefore\ndef make_metavar(value):\nafter\n"
    (tmp_path / "core.py").write_text(content, encoding="utf-8")

    result = await GrepTool().invoke(
        {
            "pattern": r"def make_metavar",
            "path": ".",
            "glob": "*.py",
            "context_lines": 1,
        },
        make_context(tmp_path),
    )

    match = result.data["matches"][0]
    assert result.success
    assert match["path"] == "core.py"
    assert match["line_number"] == 3
    assert match["byte_offset"] == len("alpha\nbefore\n".encode())
    assert match["context_before"] == ["before"]
    assert match["context_after"] == ["after"]


async def test_grep_supports_file_path_case_insensitive_and_match_limit(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("Usage\nusage\nUSAGE\n", encoding="utf-8")

    result = await GrepTool().invoke(
        {
            "pattern": "usage",
            "path": "sample.py",
            "ignore_case": True,
            "max_matches": 2,
        },
        make_context(tmp_path),
    )

    assert result.success
    assert result.data["match_count"] == 2
    assert result.data["truncated"]


async def test_grep_skips_binary_ignored_and_symlink_files(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-grep"
    outside.mkdir(exist_ok=True)
    (outside / "secret.py").write_text("needle", encoding="utf-8")
    (tmp_path / "linked.py").symlink_to(outside / "secret.py")
    (tmp_path / "image.png").write_bytes(b"needle")
    (tmp_path / "binary.txt").write_bytes(b"\x00needle")
    (tmp_path / "source.py").write_text("needle", encoding="utf-8")

    result = await GrepTool().invoke(
        {"pattern": "needle", "path": "."},
        make_context(tmp_path),
    )

    assert [match["path"] for match in result.data["matches"]] == ["source.py"]


async def test_grep_rejects_invalid_regex_and_workspace_escape(tmp_path: Path) -> None:
    invalid_regex = await GrepTool().invoke({"pattern": "["}, make_context(tmp_path))
    escaped = await GrepTool().invoke(
        {"pattern": "value", "path": ".."},
        make_context(tmp_path),
    )

    assert invalid_regex.error_code == "invalid_input"
    assert escaped.error_code == "invalid_input"
