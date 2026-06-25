"""Docker-based sandbox for isolated command execution.

Manages a Docker container with volume-mounted workspace for safe,
reproducible execution of build, test, and diagnostic commands.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path


class DockerSandboxError(RuntimeError):
    """Raised when a Docker operation fails."""


class DockerSandbox:
    """Creates and manages a sandbox container for isolated command execution.

    Usage:
        sandbox = DockerSandbox(image="python:3.11-slim", workspace="/tmp/work")
        sandbox.start()
        result = sandbox.run(["python", "-c", "print('hello')"], timeout=60)
        sandbox.stop()
    """

    def __init__(
        self,
        image: str = "python:3.11-slim",
        workspace: Path | str | None = None,
        network_disabled: bool = True,
    ) -> None:
        self._image = image
        self._workspace = Path(workspace) if workspace else Path.cwd()
        self._network_disabled = network_disabled
        self._container_name = f"nanoagent-{uuid.uuid4().hex[:8]}"
        self._running = False

    @property
    def name(self) -> str:
        return self._container_name

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Pull image and start container."""
        self._ensure_image()
        args = [
            "docker", "run", "-d", "--rm",
            "--name", self._container_name,
            "-v", f"{self._workspace.resolve()}:/workspace",
            "-w", "/workspace",
        ]
        if self._network_disabled:
            args.append("--network=none")
        args.extend(["sleep", "infinity"])
        try:
            subprocess.run(args, capture_output=True, check=True, text=True, timeout=120)
        except subprocess.CalledProcessError as exc:
            raise DockerSandboxError(
                f"Failed to start container: {exc.stderr.strip()}"
            ) from exc
        self._running = True

    def run(
        self,
        command: list[str],
        *,
        timeout: int = 600,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command inside the container.

        Returns (exit_code, stdout, stderr).
        """
        if not self._running:
            return (-1, "", "container not running")

        args = ["docker", "exec", "-i"]
        if env:
            for k, v in env.items():
                args.extend(["-e", f"{k}={v}"])
        args.append(self._container_name)
        args.extend(command)

        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return (
                -1,
                exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "",
                f"Command timed out after {timeout}s",
            )

        return (proc.returncode, proc.stdout, proc.stderr)

    def stop(self) -> None:
        """Stop and remove the container."""
        self._running = False
        try:
            subprocess.run(
                ["docker", "stop", "-t", "5", self._container_name],
                capture_output=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["docker", "kill", self._container_name],
                capture_output=True,
                timeout=10,
            )

    def _ensure_image(self) -> None:
        result = subprocess.run(
            ["docker", "image", "inspect", self._image],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["docker", "pull", self._image],
                check=True,
                timeout=300,
            )
