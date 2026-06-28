"""
Automated ablation experiment runner for nanoAgent.

Calls NanoAgent directly with config variations to run controlled A/B tests:
  --experiment compaction   ON vs OFF for context compaction
  --experiment parallelism  ON vs OFF for subagent delegation

All run artifacts land under .nano/runs/ and .nano/experiments/.

Usage:
  python3 tests/run_experiments.py --experiment compaction --repo <url> --task "<prompt>" --runs 2
  python3 tests/run_experiments.py --experiment parallelism --repo <url> --task "<prompt>" --runs 2
  python3 tests/run_experiments.py --experiment all --repo <url> --task "<prompt>" --runs 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from nano_agent.agent import NanoAgent
from nano_agent.config import AgentConfig

EXPERIMENT_DIR = PROJECT_ROOT / ".nano" / "experiments"


class Experiment:
    def __init__(self, name: str, config_updates: dict, description: str = ""):
        self.name = name
        self.config_updates = config_updates
        self.description = description


# ---------------------------------------------------------------------------
# Experiment definitions
# ---------------------------------------------------------------------------

COMPACTION_ON = Experiment(
    name="compaction_on",
    config_updates={"context_compaction_enabled": True},
    description="Compaction pipeline enabled",
)
COMPACTION_OFF = Experiment(
    name="compaction_off",
    config_updates={"context_compaction_enabled": False},
    description="Compaction pipeline disabled",
)

Subagent_ON = Experiment(
    name="subagent_on",
    config_updates={"subagents_enabled": True},
    description="Subagent delegation and background jobs enabled",
)
Subagent_OFF = Experiment(
    name="subagent_off",
    config_updates={"subagents_enabled": False},
    description="Subagent delegation disabled (sequential only)",
)

# ── Recommended repos and task prompts ─────────────────────────────────────

RECOMMENDED = {
    "compaction": {
        "repo": "https://github.com/textualize/rich",
        "task": (
            "Explore the rich source code under the rich/ directory. "
            "Read each major module's __init__.py and key source files. "
            "Run the test suite with pytest to verify everything passes. "
            "If any tests fail, read the failing test and corresponding source, "
            "then report the root cause. Finally list all public API names "
            "exported by the rich package."
        ),
        "why": (
            "rich has ~200 Python files and a test suite with output. "
            "Reading many files + running pytest generates large tool results "
            "that naturally trigger the compaction pipeline."
        ),
    },
    "parallelism": {
        "repo": "https://github.com/encode/starlette",
        "task": (
            "Audit the starlette source code for code quality issues. "
            "The project has sub-packages under starlette/ including middleware, "
            "routing, responses, staticfiles, and others. For each sub-package: "
            "check all public functions have docstrings, verify error handling "
            "patterns, and identify functions missing type annotations. "
            "You may delegate independent sub-package checks to subagents for "
            "parallel exploration. Report findings per sub-package."
        ),
        "why": (
            "starlette has multiple independent sub-packages. The task naturally "
            "decomposes into parallel per-package audits, perfect for testing "
            "subagent throughput and speedup."
        ),
    },
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def build_config(experiment: Experiment) -> AgentConfig:
    """Build AgentConfig with experiment overrides and required permissions."""
    base = {
        "allow_command": True,
        "allow_write": True,
        "llm_calls_enabled": True,
        "audit_enabled": True,
        "console_progress_enabled": True,
        "command_timeout_seconds": 600,
        "max_steps": 160,
    }
    base.update(experiment.config_updates)
    return AgentConfig(**base)


def run_one(experiment: Experiment, repo_url: str, task: str, *, timeout: int = 2400) -> dict:
    """Run the agent once and return metadata."""
    meta = {
        "experiment_name": experiment.name,
        "description": experiment.description,
        "config_updates": experiment.config_updates,
        "repo_url": repo_url,
        "task": task,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    print(f"\n  [{timestamp}] {experiment.name}: {task[:90]}...")
    sys.stdout.flush()

    config = build_config(experiment)
    agent = NanoAgent(config=config)

    started = time.monotonic()
    try:
        result = asyncio.run(agent.run(repo_url=repo_url, user_request=task))
        duration = time.monotonic() - started
        run_dir = config.runs_root / result.run_id

        meta.update({
            "run_id": result.run_id,
            "status": result.status.value,
            "steps": result.steps,
            "llm_call_count": result.llm_call_count,
            "tool_call_count": len(result.tool_calls),
            "duration_seconds": round(duration, 1),
            "run_dir": str(run_dir),
            "notes": result.notes,
        })
    except Exception as exc:
        duration = time.monotonic() - started
        meta.update({
            "status": "error",
            "duration_seconds": round(duration, 1),
            "error": f"{type(exc).__name__}: {exc}",
        })

    meta["finished_at"] = datetime.now(timezone.utc).isoformat()

    # Persist metadata
    out_dir = EXPERIMENT_DIR / experiment.name
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / f"meta_{timestamp}.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Copy run artifacts
    if meta.get("run_dir"):
        run_path = Path(meta["run_dir"])
        dest = out_dir / "runs" / run_path.name
        if run_path.exists() and not dest.exists():
            shutil.copytree(run_path, dest, symlinks=True)

    status = meta.get("status", "error")
    print(f"  [{status}] duration={meta['duration_seconds']}s steps={meta.get('steps','?')} "
          f"llm_calls={meta.get('llm_call_count','?')} → {meta_path.name}")
    sys.stdout.flush()
    return meta


def main():
    parser = argparse.ArgumentParser(description="nanoAgent ablation experiment runner")
    parser.add_argument("--experiment", choices=["compaction", "parallelism", "all"], required=True)
    parser.add_argument("--repo", help="GitHub repository URL")
    parser.add_argument("--task", help="Task prompt for the agent")
    parser.add_argument("--runs", type=int, default=2, help="Runs per variant (default: 2)")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout per run in seconds")
    parser.add_argument("--show-recommended", action="store_true", help="Print recommended repos/tasks and exit")
    args = parser.parse_args()

    if args.show_recommended:
        print(json.dumps(RECOMMENDED, indent=2, ensure_ascii=False))
        return

    repo = args.repo or RECOMMENDED.get(args.experiment, {}).get("repo", "")
    task = args.task or RECOMMENDED.get(args.experiment, {}).get("task", "")
    if not repo or not task:
        parser.error("--repo and --task required (or use --show-recommended to see defaults)")

    results: dict[str, list[dict]] = {}

    if args.experiment in ("compaction", "all"):
        print(f"\n{'='*60}")
        print(f"  COMPACTION ABLATION ({args.runs} runs per variant)")
        print(f"{'='*60}")
        results["compaction_on"] = []
        results["compaction_off"] = []
        for i in range(args.runs):
            print(f"\n── Compaction ON  [{i+1}/{args.runs}]")
            results["compaction_on"].append(run_one(COMPACTION_ON, repo, task, timeout=args.timeout))
            print(f"\n── Compaction OFF [{i+1}/{args.runs}]")
            results["compaction_off"].append(run_one(COMPACTION_OFF, repo, task, timeout=args.timeout))

    if args.experiment in ("parallelism", "all"):
        print(f"\n{'='*60}")
        print(f"  SUBAGENT PARALLELISM ABLATION ({args.runs} runs per variant)")
        print(f"{'='*60}")
        results["subagent_on"] = []
        results["subagent_off"] = []
        for i in range(args.runs):
            print(f"\n── Subagent ON  [{i+1}/{args.runs}]")
            results["subagent_on"].append(run_one(Subagent_ON, repo, task, timeout=args.timeout))
            print(f"\n── Subagent OFF [{i+1}/{args.runs}]")
            results["subagent_off"].append(run_one(Subagent_OFF, repo, task, timeout=args.timeout))

    # Summary
    print(f"\n{'='*60}")
    print("  EXPERIMENT COMPLETE")
    print(f"{'='*60}")
    for variant, metas in results.items():
        completed = [m for m in metas if m.get("status") == "completed"]
        avg_dur = sum(m["duration_seconds"] for m in metas) / len(metas) if metas else 0
        print(f"  {variant}: {len(completed)}/{len(metas)} completed, avg {avg_dur:.0f}s")

    print(f"\n  Artifacts: {EXPERIMENT_DIR}")
    print(f"  Analyze:   python3 tests/analyze_runs.py --run-dir .nano/experiments/<variant>/runs/<run_id>")


if __name__ == "__main__":
    main()
