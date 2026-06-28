import asyncio
import os
import time
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.runtime.environment import ExecutionEnvironmentManager


def test_environment_redirects_package_manager_state(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "run-1" / "runtime"
    manager = ExecutionEnvironmentManager(runtime_dir, AgentConfig())

    environment = manager.build_environment()

    assert environment["HOME"] == str(runtime_dir / "home")
    assert environment["TMPDIR"] == str(runtime_dir / "tmp")
    assert environment["PIP_CACHE_DIR"] == str(runtime_dir / "pip-cache")
    assert environment["npm_config_prefix"] == str(runtime_dir / "npm-prefix")
    assert environment["npm_config_cache"] == str(runtime_dir / "npm-cache")
    assert environment["CARGO_HOME"] == str(runtime_dir / "cargo-home")
    assert environment["CARGO_INSTALL_ROOT"] == str(runtime_dir / "cargo-install")
    assert environment["GOPATH"] == str(runtime_dir / "go")
    assert environment["GOCACHE"] == str(runtime_dir / "go-cache")
    assert "VIRTUAL_ENV" not in environment


async def test_python_environments_are_scoped_to_individual_runs(tmp_path: Path) -> None:
    first = ExecutionEnvironmentManager(tmp_path / "run-1" / "runtime", AgentConfig())
    second = ExecutionEnvironmentManager(tmp_path / "run-2" / "runtime", AgentConfig())

    first_python = await first.resolve_program_async("python3")
    second_python = await second.resolve_program_async("python3")

    assert first_python != second_python
    assert first.runtime_dir in first_python.parents
    assert second.runtime_dir in second_python.parents


async def test_python_environment_setup_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    class SlowVenvProcess:
        returncode = 0
        pid = 999_999

        async def communicate(self):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.2)
            return b"", b""

    async def fake_create_subprocess_exec(*argv, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        venv = Path(argv[-1])
        bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / ("python.exe" if os.name == "nt" else "python")).touch()
        return SlowVenvProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    manager = ExecutionEnvironmentManager(tmp_path / "run-1" / "runtime", AgentConfig())

    started = time.monotonic()
    task = asyncio.create_task(manager.resolve_program_async("python3"))
    await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    elapsed = time.monotonic() - started
    resolved = await task

    assert elapsed < 0.15
    assert resolved == manager._python_program_path("python3")  # noqa: SLF001
