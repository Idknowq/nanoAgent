from __future__ import annotations

import json
from pathlib import Path
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

    value = _public_result_payload(result)
    return _bounded_mapping(value, max_result_chars)


def _public_result_payload(result: SubagentResult) -> dict[str, Any]:
    """Build the public result payload before applying the character budget."""

    value = result.model_dump(mode="json")
    report = value.get("completion_report")
    payload = {
        "subagent_id": value["subagent_id"],
        "parent_run_id": value["parent_run_id"],
        "status": value["status"],
        "error_kind": value.get("error_kind"),
        "error": value.get("error"),
        "steps_used": value.get("steps_used", 0),
        "llm_calls_used": value.get("llm_calls_used", 0),
        "completion_report": report,
        "full_result": _full_result_reference(result),
    }
    if report is None:
        payload["output"] = value.get("output")
    return payload


def _bounded_mapping(value: dict[str, Any], limit: int) -> dict[str, Any]:
    if len(json.dumps(value, ensure_ascii=False)) <= limit:
        return value
    report = value.get("completion_report")
    compact = {
        "subagent_id": value["subagent_id"],
        "parent_run_id": value["parent_run_id"],
        "status": value["status"],
        "error_kind": value.get("error_kind"),
        "error": value.get("error"),
        "steps_used": value.get("steps_used", 0),
        "llm_calls_used": value.get("llm_calls_used", 0),
        "completion_report": _compact_report(report, limit) if report is not None else None,
        "full_result": value.get("full_result"),
    }
    if report is None:
        compact["output"] = _truncate(value.get("output") or "", limit // 4)
    compact["error"] = _truncate(compact.get("error") or "", limit // 8)
    if len(json.dumps(compact, ensure_ascii=False)) <= limit:
        return compact
    return {
        "subagent_id": _truncate(str(value["subagent_id"]), limit // 4),
        "status": value["status"],
        "truncated": True,
        "full_result": value.get("full_result"),
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


def _full_result_reference(result: SubagentResult) -> dict[str, Any]:
    """Return run-relative artifact paths for retrieving the complete result."""

    run_dir = Path(result.run_dir)
    base = Path("subagents") / run_dir.name
    return {
        "available": True,
        "artifact_path": str(base / result.result_path),
        "summary_path": str(base / result.summary_path),
        "messages_path": str(base / result.messages_path),
    }
