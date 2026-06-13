from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from nano_agent.models import CompletionReport, RunSummary


class ReportStore:
    """Render and atomically persist the user-facing Markdown completion report."""

    filename = "report.md"  # 每个 run 的最终用户报告文件名。

    def save(self, run_dir: Path, run: RunSummary, report: CompletionReport) -> Path:
        target = run_dir / self.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        content = self.render(run, report)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, target)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return target

    def render(self, run: RunSummary, report: CompletionReport) -> str:
        changed_files = self._list(report.changed_files, "None", code=True)
        risks = self._list(report.remaining_risks, "None")
        blockers = self._list(report.blockers, "None")
        duration = (
            max(0.0, (run.finished_at - run.started_at).total_seconds())
            if run.finished_at is not None
            else 0.0
        )
        return (
            "# nanoAgent Run Report\n\n"
            "## Outcome\n\n"
            f"**Status:** {report.status.value}\n\n"
            "## Problem\n\n"
            f"{report.problem.strip()}\n\n"
            "## Root Cause\n\n"
            f"{report.root_cause.strip()}\n\n"
            "## Resolution\n\n"
            f"{report.resolution.strip()}\n\n"
            "## Files Changed\n\n"
            f"{changed_files}\n\n"
            "## Verification\n\n"
            f"{report.verification_summary.strip() or 'Not completed.'}\n\n"
            "## Remaining Risks\n\n"
            f"{risks}\n\n"
            "## Blockers\n\n"
            f"{blockers}\n\n"
            "## Run Information\n\n"
            f"- Steps: {run.steps}\n"
            f"- LLM calls: {run.llm_call_count}\n"
            f"- Tool calls: {len(run.tool_calls)}\n"
            f"- Duration: {duration:.2f} seconds\n"
        )

    @staticmethod
    def _list(values: list[str], empty_text: str, *, code: bool = False) -> str:
        if not values:
            return f"- {empty_text}"
        if code:
            return "\n".join(f"- `{value}`" for value in values)
        return "\n".join(f"- {value}" for value in values)
