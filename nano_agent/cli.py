from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console

from nano_agent.agent import NanoAgent
from nano_agent.config import AgentConfig

app = typer.Typer(help="nanoAgent repository diagnosis CLI.")
console = Console()


@app.callback()
def main() -> None:
    """nanoAgent repository diagnosis CLI."""


@app.command()
def run(
    repo_url: Annotated[str, typer.Argument(help="Git repository URL to analyze.")],
    workdir: Annotated[
        Path,
        typer.Option("--workdir", help="Directory for isolated agent workspaces."),
    ] = Path(".nano/workspaces"),
    max_steps: Annotated[
        int,
        typer.Option("--max-steps", min=1, help="Maximum agent execution steps."),
    ] = 20,
    auto_approve: Annotated[
        bool,
        typer.Option("--auto-approve", help="Allow risky command execution without prompting."),
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
        auto_approve=auto_approve,
        llm_provider=llm,
        llm_model=model,
    )
    agent = NanoAgent(config=config)
    result = agent.run(repo_url=repo_url)

    console.print("\n[bold]Run summary[/bold]")
    console.print_json(result.model_dump_json(indent=2))
