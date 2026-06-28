import asyncio
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.tools.base import ToolContext
from nano_agent.tools.clone_repo import CloneRepoTool

REPO_URL = "https://github.com/example/repo.git"


def make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        run_id="test",
        repo_url=REPO_URL,
        workspace_path=tmp_path / "workspace",
        run_dir=tmp_path / "runs" / "test",
        config=AgentConfig(workspace_root=tmp_path),
    )


class FakeGitProcess:
    """Async subprocess stand-in used by clone_repo tests."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        timeout: bool = False,
    ) -> None:
        self.stdout = stdout.encode()
        self.stderr = stderr.encode()
        self.returncode = returncode
        self.timeout = timeout
        self.pid = 999_999
        self.communicate_calls = 0

    async def communicate(self):  # type: ignore[no-untyped-def]
        self.communicate_calls += 1
        if self.timeout and self.communicate_calls == 1:
            raise TimeoutError
        return self.stdout, self.stderr


def completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> FakeGitProcess:
    return FakeGitProcess(stdout=stdout, stderr=stderr, returncode=returncode)


async def test_clone_repo_clones_and_returns_repository_metadata(tmp_path: Path, monkeypatch) -> None:
    responses = iter(
        [
            completed(),
            completed("abc123\n"),
            completed("main\n"),
            completed(f"{REPO_URL}\n"),
        ]
    )
    calls: list[list[str]] = []

    async def fake_create_subprocess_exec(*argv, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        calls.append(list(argv))
        return next(responses)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    context = make_context(tmp_path)

    result = await CloneRepoTool().invoke({"repo_url": REPO_URL, "depth": 1}, context)

    assert result.success
    assert result.data["commit"] == "abc123"
    assert result.data["branch"] == "main"
    assert result.data["remote_url"] == REPO_URL
    assert result.data["workspace"] == "."
    assert calls[0] == ["git", "clone", "--depth", "1", "--", REPO_URL, "."]
    assert context.workspace_path.is_dir()


async def test_clone_repo_rejects_nonempty_workspace(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    context.workspace_path.mkdir()
    (context.workspace_path / "existing.txt").touch()

    result = await CloneRepoTool().invoke({"repo_url": REPO_URL}, context)

    assert result.error_code == "invalid_input"
    assert "empty" in result.error_message


async def test_clone_repo_rejects_untrusted_or_mismatched_url(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    local = await CloneRepoTool().invoke({"repo_url": "file:///tmp/repo"}, context)
    mismatched = await CloneRepoTool().invoke(
        {"repo_url": "https://github.com/other/repo.git"},
        context,
    )

    assert local.error_code == "invalid_input"
    assert mismatched.error_code == "invalid_input"
    assert "current run" in mismatched.error_message


async def test_clone_repo_returns_git_failure_details(tmp_path: Path, monkeypatch) -> None:
    async def fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return completed(stderr="authentication failed", returncode=128)

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await CloneRepoTool().invoke({"repo_url": REPO_URL}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "clone_failed"
    assert result.data["exit_code"] == 128
    assert result.data["stderr_tail"] == "authentication failed"


async def test_clone_repo_returns_timeout(tmp_path: Path, monkeypatch) -> None:
    async def fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return FakeGitProcess(timeout=True)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await CloneRepoTool().invoke({"repo_url": REPO_URL}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "timeout"


async def test_clone_repo_returns_missing_git_error(tmp_path: Path, monkeypatch) -> None:
    async def raise_missing(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", raise_missing)

    result = await CloneRepoTool().invoke({"repo_url": REPO_URL}, make_context(tmp_path))

    assert result.error_code == "execution_error"
    assert "not found" in result.error_message
