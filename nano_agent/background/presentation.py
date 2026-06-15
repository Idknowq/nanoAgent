from __future__ import annotations

import json
from typing import Any

from nano_agent.background.models import BackgroundJob
from nano_agent.subagents.models import SubagentResult


def public_job_data(job: BackgroundJob, max_result_chars: int) -> dict[str, Any]:
    """Return a bounded LLM-facing Job representation without internal paths."""

    data = job.model_dump(
        mode="json",
        exclude={
            "result": {
                "run_dir",
                "result_path",
                "summary_path",
                "messages_path",
            }
        },
    )
    if job.result is not None:
        data["result"] = public_subagent_result(job.result, max_result_chars)
    data["task_managed_by_job"] = job.task_id is not None
    return data


def public_subagent_result(
    result: SubagentResult,
    max_result_chars: int,
) -> dict[str, Any]:
    """Return a bounded LLM-facing Subagent result without run-internal paths."""

    value = result.model_dump(
        mode="json",
        exclude={"run_dir", "result_path", "summary_path", "messages_path"},
    )
    return _bounded_mapping(value, max_result_chars)


def _bounded_mapping(value: dict[str, Any], limit: int) -> dict[str, Any]:
    if len(json.dumps(value, ensure_ascii=False)) <= limit:
        return value
    report = value.get("completion_report")
    compact = {
        "subagent_id": value["subagent_id"],
        "parent_run_id": value["parent_run_id"],
        "status": value["status"],
        "output": value.get("output"),
        "error_kind": value.get("error_kind"),
        "error": value.get("error"),
        "steps_used": value.get("steps_used", 0),
        "llm_calls_used": value.get("llm_calls_used", 0),
        "completion_report": _compact_report(report, limit) if report is not None else None,
    }
    compact["output"] = _truncate(compact.get("output") or "", limit // 4)
    compact["error"] = _truncate(compact.get("error") or "", limit // 8)
    if len(json.dumps(compact, ensure_ascii=False)) <= limit:
        return compact
    return {
        "subagent_id": _truncate(str(value["subagent_id"]), limit // 4),
        "status": value["status"],
        "truncated": True,
    }


def _compact_report(report: dict[str, Any], limit: int) -> dict[str, Any]:
    text_limit = max(16, limit // 20)
    list_limit = max(1, min(3, limit // 1000))
    return {
        "status": report["status"],
        "problem": _truncate(report.get("problem", ""), text_limit),
        "root_cause": _truncate(report.get("root_cause", ""), text_limit),
        "resolution": _truncate(report.get("resolution", ""), text_limit),
        "changed_files": [
            _truncate(str(item), text_limit)
            for item in report.get("changed_files", [])[:list_limit]
        ],
        "verification_summary": _truncate(
            report.get("verification_summary", ""),
            text_limit,
        ),
        "remaining_risks": [
            _truncate(str(item), text_limit)
            for item in report.get("remaining_risks", [])[:list_limit]
        ],
        "blockers": [
            _truncate(str(item), text_limit)
            for item in report.get("blockers", [])[:list_limit]
        ],
    }


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = "...[truncated]"
    return value[: max(0, limit - len(marker))] + marker
