from __future__ import annotations

import asyncio
import os
import shutil
import signal
import sys
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.tools.errors import ToolExecutionError


class ExecutionEnvironmentManager:
    """Prepare and resolve programs inside one run-scoped execution environment."""

    _PYTHON_PROGRAMS = frozenset(
        {"python", "python3", "pytest", "ruff", "pip"}
    )  # 必须从隔离虚拟环境解析的 Python 工具。

    def __init__(self, runtime_dir: Path, config: AgentConfig) -> None:
        self.runtime_dir = runtime_dir.resolve()  # 当前 run 的隔离执行环境绝对路径。
        self.config = config  # 当前 Agent 的全局配置。
        self.python_venv = self.runtime_dir / "python" / "venv"  # Python 虚拟环境目录。
        self.home_dir = self.runtime_dir / "home"  # 命令使用的隔离 HOME。
        self.tmp_dir = self.runtime_dir / "tmp"  # 命令使用的临时文件目录。

    def resolve_program(self, program: str) -> Path:
        """Resolve an allowlisted program without falling back to the host Python environment."""
        if not self.config.execution_isolation_enabled:
            resolved = shutil.which(program)
            if resolved is None:
                raise ToolExecutionError(f"executable was not found: {program}")
            return Path(resolved)

        self._ensure_directories()
        if program in self._PYTHON_PROGRAMS:
            raise ToolExecutionError(
                "isolated Python program resolution requires resolve_program_async"
            )
        resolved = shutil.which(program, path=self._system_path())
        if resolved is None:
            raise ToolExecutionError(f"executable was not found: {program}")
        return Path(resolved)

    async def resolve_program_async(self, program: str) -> Path:
        """Resolve an allowlisted program without blocking on environment setup."""
        if not self.config.execution_isolation_enabled:
            resolved = shutil.which(program)
            if resolved is None:
                raise ToolExecutionError(f"executable was not found: {program}")
            return Path(resolved)

        self._ensure_directories()
        if program in self._PYTHON_PROGRAMS:
            await self.ensure_python_environment_async()
            resolved = self._python_program_path(program)
            if not resolved.is_file():
                raise ToolExecutionError(
                    f"{program} is not installed in the isolated run environment"
                )
            return resolved

        resolved = shutil.which(program, path=self._system_path())
        if resolved is None:
            raise ToolExecutionError(f"executable was not found: {program}")
        return Path(resolved)

    def ensure_python_environment(self) -> Path:
        """Create a dedicated Python virtual environment for the current run."""
        if self.config.execution_isolation_enabled:
            raise ToolExecutionError(
                "isolated Python environment setup requires ensure_python_environment_async"
            )
        return self.python_venv

    async def ensure_python_environment_async(self) -> Path:
        """Create a dedicated Python virtual environment for the current run."""
        ready_marker = self.python_venv / ".nano-agent-ready"
        python_path = self._python_program_path("python3")
        if ready_marker.is_file() and python_path.is_file():
            return self.python_venv

        if self.python_venv.exists():
            shutil.rmtree(self.python_venv)
        self.python_venv.parent.mkdir(parents=True, exist_ok=True)
        source_python = self.config.python_executable or Path(sys.executable)
        try:
            process = await asyncio.create_subprocess_exec(
                str(source_python),
                "-m",
                "venv",
                str(self.python_venv),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(self.config.command_timeout_seconds, 30),
            )
        except TimeoutError as exc:
            await self._terminate_process_group(process)
            raise ToolExecutionError(
                "failed to create isolated Python environment: "
                f"venv command exceeded {max(self.config.command_timeout_seconds, 30)}s"
            ) from exc
        except OSError as exc:
            raise ToolExecutionError(
                f"failed to create isolated Python environment: {exc}"
            ) from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace") or stdout.decode(
                "utf-8",
                errors="replace",
            )
            raise ToolExecutionError(
                f"failed to create isolated Python environment: {detail}"
            )

        ready_marker.write_text("ready\n", encoding="utf-8")
        return self.python_venv

    async def _terminate_process_group(self, process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.communicate(), timeout=2)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.communicate()

    def build_environment(self) -> dict[str, str]:
        """Build environment variables that redirect mutable package state into the run."""
        if not self.config.execution_isolation_enabled:
            return self._legacy_environment()

        self._ensure_directories()
        environment: dict[str, str] = {
            "HOME": str(self.home_dir),
            "PATH": self._system_path(),
            "TMPDIR": str(self.tmp_dir),
            "PYTHONNOUSERSITE": "1",
            "PYTHONUSERBASE": str(self.runtime_dir / "python" / "user"),
            "PIP_REQUIRE_VIRTUALENV": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CACHE_DIR": str(self.runtime_dir / "pip-cache"),
            "npm_config_prefix": str(self.runtime_dir / "npm-prefix"),
            "npm_config_cache": str(self.runtime_dir / "npm-cache"),
            "CARGO_HOME": str(self.runtime_dir / "cargo-home"),
            "CARGO_INSTALL_ROOT": str(self.runtime_dir / "cargo-install"),
            "GOPATH": str(self.runtime_dir / "go"),
            "GOCACHE": str(self.runtime_dir / "go-cache"),
            "XDG_CACHE_HOME": str(self.runtime_dir / "xdg-cache"),
            "XDG_CONFIG_HOME": str(self.runtime_dir / "xdg-config"),
            "XDG_DATA_HOME": str(self.runtime_dir / "xdg-data"),
        }
        for name in ("LANG", "LC_ALL"):
            if value := os.environ.get(name):
                environment[name] = value

        if self.python_venv.exists():
            environment["VIRTUAL_ENV"] = str(self.python_venv)
            environment["PATH"] = os.pathsep.join(
                [str(self._python_bin_dir()), environment["PATH"]]
            )
        if rustup_home := os.environ.get("RUSTUP_HOME"):
            environment["RUSTUP_HOME"] = rustup_home
        return environment

    def _ensure_directories(self) -> None:
        directories = (
            self.home_dir,
            self.tmp_dir,
            self.runtime_dir / "pip-cache",
            self.runtime_dir / "npm-prefix",
            self.runtime_dir / "npm-cache",
            self.runtime_dir / "cargo-home",
            self.runtime_dir / "cargo-install",
            self.runtime_dir / "go",
            self.runtime_dir / "go-cache",
            self.runtime_dir / "xdg-cache",
            self.runtime_dir / "xdg-config",
            self.runtime_dir / "xdg-data",
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def _python_program_path(self, program: str) -> Path:
        executable_name = program
        if program in {"python", "python3"}:
            executable_name = "python.exe" if os.name == "nt" else "python"
        return self._python_bin_dir() / executable_name

    def _python_bin_dir(self) -> Path:
        return self.python_venv / ("Scripts" if os.name == "nt" else "bin")

    def _system_path(self) -> str:
        """Remove the active nanoAgent virtualenv from executable lookup."""
        inherited = os.environ.get("PATH", os.defpath).split(os.pathsep)
        excluded: set[str] = set()
        if sys.prefix != sys.base_prefix:
            excluded.add(str(Path(sys.executable).resolve().parent))
        if active_venv := os.environ.get("VIRTUAL_ENV"):
            active_bin = Path(active_venv) / ("Scripts" if os.name == "nt" else "bin")
            excluded.add(str(active_bin.resolve()))
        filtered = [
            entry for entry in inherited if entry and str(Path(entry).resolve()) not in excluded
        ]
        return os.pathsep.join(filtered) or os.defpath

    def _legacy_environment(self) -> dict[str, str]:
        allowed_names = {"HOME", "LANG", "LC_ALL", "PATH", "TMPDIR", "VIRTUAL_ENV"}
        environment = {name: value for name, value in os.environ.items() if name in allowed_names}
        environment.setdefault("PATH", os.defpath)
        return environment
