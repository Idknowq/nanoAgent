from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from nano_agent.agent import NanoAgent
from nano_agent.config import AgentConfig

load_dotenv()

app = typer.Typer(help="nanoAgent repository diagnosis CLI.")
console = Console()
default_config = AgentConfig()  # CLI 未提供覆盖参数时使用的 Agent 默认配置。


@app.callback()
def main() -> None:
    """nanoAgent repository diagnosis CLI."""


@app.command()
def run(
    repo_url: Annotated[str, typer.Argument(help="Git repository URL to analyze.")],
    user_request: Annotated[str, typer.Argument(help="Repository task to complete.")],
    workdir: Annotated[
        Path,
        typer.Option("--workdir", help="Directory for isolated agent workspaces."),
    ] = Path(".nano/workspaces"),
    max_steps: Annotated[
        int,
        typer.Option("--max-steps", min=1, help="Maximum agent execution steps."),
    ] = default_config.max_steps,
    background_idle_wait_timeout: Annotated[
        float,
        typer.Option(
            "--background-idle-wait-timeout",
            min=0.1,
            max=120,
            help="Seconds to wait when only active background Jobs remain.",
        ),
    ] = default_config.background_idle_wait_timeout_seconds,
    allow_command: Annotated[
        bool,
        typer.Option("--allow-command", help="Allow risky command execution."),
    ] = False,
    allow_write: Annotated[
        bool,
        typer.Option("--allow-write", help="Allow workspace file edits."),
    ] = False,
    llm: Annotated[
        Literal["deepseek"],
        typer.Option("--llm", help="LLM backend to use."),
    ] = "deepseek",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Override provider model name."),
    ] = None,
) -> None:
    """Run the single-agent tool-use loop for a repository."""
    config = AgentConfig(
        workspace_root=workdir,
        max_steps=max_steps,
        background_idle_wait_timeout_seconds=background_idle_wait_timeout,
        allow_command=allow_command,
        allow_write=allow_write,
        llm_provider=llm,
        llm_model=model,
    )
    agent = NanoAgent(config=config)
    result = agent.run(repo_url=repo_url, user_request=user_request)

    successful_tools = sum(call.success for call in result.tool_calls)
    failed_tools = len(result.tool_calls) - successful_tools
    duration = (
        max(0.0, (result.finished_at - result.started_at).total_seconds())
        if result.finished_at is not None
        else 0.0
    )
    status = result.status.value
    status_style = {
        "completed": "bold green",
        "blocked": "bold yellow",
        "failed": "bold red",
    }.get(status, "bold")
    content = Text()
    content.append("Status      ")
    content.append(status, style=status_style)
    content.append(f"\nSteps       {result.steps}")
    content.append(f"\nLLM calls   {result.llm_call_count}")
    content.append(f"\nTools       {successful_tools} succeeded / {failed_tools} failed")
    content.append(f"\nDuration    {duration:.2f}s")
    content.append(f"\nReport      {config.runs_root / result.run_id / 'report.md'}", style="cyan")
    console.print()
    console.print(Panel(content, title="nanoAgent", border_style=status_style))
