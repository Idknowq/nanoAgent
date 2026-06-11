import subprocess
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


def completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["git"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_clone_repo_clones_and_returns_repository_metadata(tmp_path: Path, monkeypatch) -> None:
    responses = iter(
        [
            completed(),
            completed("abc123\n"),
            completed("main\n"),
            completed(f"{REPO_URL}\n"),
        ]
    )
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(argv)
        return next(responses)

    monkeypatch.setattr(subprocess, "run", fake_run)
    context = make_context(tmp_path)

    result = CloneRepoTool().invoke({"repo_url": REPO_URL, "depth": 1}, context)

    assert result.success
    assert result.data["commit"] == "abc123"
    assert result.data["branch"] == "main"
    assert result.data["remote_url"] == REPO_URL
    assert calls[0] == ["git", "clone", "--depth", "1", "--", REPO_URL, "."]
    assert context.workspace_path.is_dir()


def test_clone_repo_rejects_nonempty_workspace(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    context.workspace_path.mkdir()
    (context.workspace_path / "existing.txt").touch()

    result = CloneRepoTool().invoke({"repo_url": REPO_URL}, context)

    assert result.error_code == "invalid_input"
    assert "empty" in result.error_message


def test_clone_repo_rejects_untrusted_or_mismatched_url(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    local = CloneRepoTool().invoke({"repo_url": "file:///tmp/repo"}, context)
    mismatched = CloneRepoTool().invoke(
        {"repo_url": "https://github.com/other/repo.git"},
        context,
    )

    assert local.error_code == "invalid_input"
    assert mismatched.error_code == "invalid_input"
    assert "current run" in mismatched.error_message


def test_clone_repo_returns_git_failure_details(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: completed(stderr="authentication failed", returncode=128),
    )

    result = CloneRepoTool().invoke({"repo_url": REPO_URL}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "clone_failed"
    assert result.data["exit_code"] == 128
    assert result.data["stderr_tail"] == "authentication failed"


def test_clone_repo_returns_timeout(tmp_path: Path, monkeypatch) -> None:
    def raise_timeout(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="git", timeout=120)

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    result = CloneRepoTool().invoke({"repo_url": REPO_URL}, make_context(tmp_path))

    assert not result.success
    assert result.error_code == "timeout"


def test_clone_repo_returns_missing_git_error(tmp_path: Path, monkeypatch) -> None:
    def raise_missing(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", raise_missing)

    result = CloneRepoTool().invoke({"repo_url": REPO_URL}, make_context(tmp_path))

    assert result.error_code == "execution_error"
    assert "not found" in result.error_message
