"""
Offline analysis of nanoAgent run artifacts.

Computes ablation-study metrics from .nano/runs/<run_id>/ artifacts:
  1. Skill two-stage loading: static token reduction from deferring skill bodies
  2. Context compaction: input token compression ratio, post-compaction cache hit rate
  3. Subagent parallelism: time savings and token comparison vs sequential baseline

Usage:
  python tests/analyze_runs.py [--run-dir .nano/runs/<run_id>] [--all-runs] [--skill-only] [--compact-only] [--parallel-only]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Skill two-stage loading analysis (static, no run needed)
# ---------------------------------------------------------------------------

SKILLS_ROOT = Path(__file__).resolve().parent.parent / "nano_agent" / "skills" / "builtin"


def _read_skill_frontmatter_and_body(path: Path) -> tuple[dict, str]:
    """Read a SKILL.md file, returning (frontmatter_dict, body_text)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 2:
        return {}, text
    import yaml
    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        frontmatter = {}
    body = parts[2].strip() if len(parts) > 2 else ""
    return frontmatter, body


def analyze_skill_loading() -> dict:
    """Calculate token savings from two-stage skill loading.

    One-stage (hypothetical): all skill bodies injected into initial prompt.
    Two-stage (current): only metadata in initial prompt; body loaded on demand.

    Returns token counts using the project's conservative 3 chars/token ratio.
    """
    skills = []
    for skill_dir in sorted(SKILLS_ROOT.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        frontmatter, body = _read_skill_frontmatter_and_body(skill_file)
        name = frontmatter.get("name", skill_dir.name)
        description = frontmatter.get("description", "")

        # Metadata-only injection (current two-stage approach)
        metadata_chars = len(f"<skill><name>{name}</name><description>{description}</description></skill>")
        # Full injection would include the body instructions
        full_chars = metadata_chars + len(body)
        skills.append({
            "name": name,
            "metadata_chars": metadata_chars,
            "body_chars": len(body),
            "full_chars": full_chars,
            "ratio": metadata_chars / full_chars if full_chars > 0 else 0,
        })

    total_two_stage = sum(s["metadata_chars"] for s in skills)
    total_one_stage = sum(s["full_chars"] for s in skills)
    chars_per_token = 3  # project's conservative ratio

    return {
        "skills": skills,
        "total_skills": len(skills),
        "two_stage_chars": total_two_stage,
        "one_stage_chars": total_one_stage,
        "two_stage_estimated_tokens": max(1, total_two_stage // chars_per_token),
        "one_stage_estimated_tokens": max(1, total_one_stage // chars_per_token),
        "saved_chars": total_one_stage - total_two_stage,
        "saved_estimated_tokens": max(1, (total_one_stage - total_two_stage) // chars_per_token),
        "savings_pct": (
            round((1 - total_two_stage / total_one_stage) * 100, 1)
            if total_one_stage > 0
            else 0
        ),
    }


# ---------------------------------------------------------------------------
# Context compaction analysis (needs completed runs)
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _count_tool_result_budget_events(run_dir: Path) -> int:
    """Count L1 compaction events (tool_result_budget)."""
    return sum(
        1
        for tr_dir in _tool_result_budget_dirs(run_dir)
        for f in tr_dir.iterdir()
        if f.suffix == ".json"
    )


def _tool_result_budget_dirs(run_dir: Path) -> list[Path]:
    """Return current and legacy L1 tool-result artifact directories."""
    dirs: list[Path] = []
    summary = _load_json(run_dir / "summary.json") or {}
    workspace_path = summary.get("workspace_path")
    if workspace_path:
        workspace_dir = Path(workspace_path) / ".nano-agent" / "tool-results"
        if workspace_dir.exists():
            dirs.append(workspace_dir)

    legacy_dir = run_dir / "tool-results"
    if legacy_dir.exists() and legacy_dir not in dirs:
        dirs.append(legacy_dir)
    return dirs


def _estimate_tool_result_budget_savings(run_dir: Path) -> dict:
    """Estimate token savings from L1 tool_result_budget compaction.

    Each file in .nano-agent/tool-results/ or the legacy run_dir/tool-results/
    replaced a large tool result with a short placeholder. Returns estimated savings.
    """
    tr_dirs = _tool_result_budget_dirs(run_dir)
    if not tr_dirs:
        return {"count": 0, "estimated_chars_saved": 0, "estimated_tokens_saved": 0}

    total_chars_on_disk = 0
    count = 0
    for tr_dir in tr_dirs:
        for f in tr_dir.iterdir():
            if f.suffix == ".json":
                try:
                    total_chars_on_disk += len(f.read_text(encoding="utf-8"))
                    count += 1
                except Exception:
                    pass
    # Each persisted result was replaced by ~80-char preview in context
    chars_saved = total_chars_on_disk - (count * 80)
    return {
        "count": count,
        "total_chars_persisted": total_chars_on_disk,
        "estimated_chars_saved": max(0, chars_saved),
        "estimated_tokens_saved": max(0, chars_saved // 3),
    }


def analyze_compaction(run_dir: Path) -> dict:
    """Analyze compaction events for a single run.

    Compaction levels:
    - L1 tool_result_budget: persist large results to disk, replace in context with preview
    - L2 snip_compact: trim middle messages
    - L3 micro_compact: placeholder old results
    - L4 auto_compact: LLM summary (recorded in compactions.jsonl)
    - Reactive: emergency compact on transient failure (recorded in compactions.jsonl)

    L1-L3 are stateless transforms that don't write to compactions.jsonl.
    Only L4 auto_compact and reactive events are recorded there.
    """
    compactions = _load_jsonl(run_dir / "compactions.jsonl")
    llm_calls = _load_jsonl(run_dir / "llm_calls.jsonl")
    summary = _load_json(run_dir / "summary.json")

    # L1 tool_result_budget events (from tool-results/ directory)
    l1_budget = _estimate_tool_result_budget_savings(run_dir)

    # Parse L4 auto_compact and reactive events from compactions.jsonl
    auto_events = [c for c in compactions if c.get("compaction_type") == "auto"]
    reactive_events = [c for c in compactions if c.get("compaction_type") == "reactive"]

    auto_metrics = []
    for event in auto_events:
        before = event.get("before_estimated_tokens", 0)
        after = event.get("after_estimated_tokens", 0)
        success = event.get("success", False)
        auto_metrics.append({
            "attempt": event.get("attempt", 0),
            "before_tokens": before,
            "after_tokens": after,
            "reduction_tokens": before - after,
            "compression_ratio": round(before / after, 2) if after > 0 else 0,
            "reduction_pct": round((1 - after / before) * 100, 1) if before > 0 else 0,
            "success": success,
            "transcript": event.get("transcript_path", ""),
        })

    reactive_metrics = []
    for event in reactive_events:
        before = event.get("before_estimated_tokens", 0)
        after = event.get("after_estimated_tokens", 0)
        success = event.get("success", False)
        reactive_metrics.append({
            "attempt": event.get("attempt", 0),
            "before_tokens": before,
            "after_tokens": after,
            "reduction_tokens": before - after,
            "compression_ratio": round(before / after, 2) if after > 0 else 0,
            "reduction_pct": round((1 - after / before) * 100, 1) if before > 0 else 0,
            "success": success,
        })

    # Cache hit rate over time: first 10 vs last 10 calls
    first_10_cache = None
    last_10_cache = None
    calls_with_cache = []
    for call in llm_calls:
        cached = call.get("cached_tokens")
        input_t = call.get("input_tokens")
        if cached is not None and input_t is not None and input_t > 0:
            calls_with_cache.append(cached / input_t)
    if len(calls_with_cache) >= 20:
        first_10_cache = round(sum(calls_with_cache[:10]) / 10, 4)
        last_10_cache = round(sum(calls_with_cache[-10:]) / 10, 4)

    # Overall LLM call stats
    total_input = sum(c.get("input_tokens", 0) or 0 for c in llm_calls)
    total_output = sum(c.get("output_tokens", 0) or 0 for c in llm_calls)
    total_cached = sum(c.get("cached_tokens", 0) or 0 for c in llm_calls)
    successful_calls = [c for c in llm_calls if c.get("attempt_type") != "transient_retry"]
    failed_calls = [c for c in llm_calls if c.get("attempt_type") == "transient_retry"]

    return {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "status": summary.get("status") if summary else "unknown",
        "duration_seconds": summary.get("duration_seconds") if summary else None,
        "steps": summary.get("steps") if summary else 0,
        "llm_call_count": len(llm_calls),
        "tool_call_count": summary.get("tool_call_count") if summary else 0,
        # All compaction levels
        "l1_tool_result_budget": l1_budget,
        "l4_auto_compactions": len(auto_events),
        "reactive_compactions": len(reactive_events),
        "compaction_events_total": l1_budget["count"] + len(auto_events) + len(reactive_events),
        "auto_metrics": auto_metrics,
        "reactive_metrics": reactive_metrics,
        # Compaction summary
        "total_auto_reduction_tokens": sum(m["reduction_tokens"] for m in auto_metrics if m["success"]),
        # LLM metrics
        "successful_llm_calls": len(successful_calls),
        "failed_llm_calls": len(failed_calls),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cached_tokens": total_cached,
        "avg_input_tokens": round(total_input / len(llm_calls), 0) if llm_calls else 0,
        "avg_output_tokens": round(total_output / len(llm_calls), 0) if llm_calls else 0,
        "overall_cache_hit_rate": round(total_cached / total_input, 4) if total_input > 0 else 0,
        "cache_hit_first_10": first_10_cache,
        "cache_hit_last_10": last_10_cache,
    }


# ---------------------------------------------------------------------------
# Subagent parallelism analysis (needs completed runs with subagents)
# ---------------------------------------------------------------------------

def _load_background_jobs(run_dir: Path) -> list[dict]:
    jobs_dir = run_dir / "background" / "jobs"
    if not jobs_dir.exists():
        return []
    jobs = []
    for job_file in sorted(jobs_dir.glob("*.json")):
        data = _load_json(job_file)
        if data:
            jobs.append(data)
    return jobs


def analyze_parallelism(run_dir: Path) -> dict:
    """Analyze subagent parallelism efficiency.

    Compares wall-clock time of parallel execution vs estimated sequential time.
    """
    summary = _load_json(run_dir / "summary.json")
    jobs = _load_background_jobs(run_dir)
    llm_calls = _load_jsonl(run_dir / "llm_calls.jsonl")
    audit = _load_jsonl(run_dir / "audit.jsonl")

    # Only relevant if background jobs were used
    if not jobs:
        return {
            "run_id": run_dir.name,
            "has_subagents": False,
            "message": "No background jobs found in this run.",
        }

    # Job metrics
    job_metrics = []
    for job in jobs:
        started = job.get("started_at")
        finished = job.get("finished_at")
        created = job.get("created_at")
        duration = None
        queue_time = None
        if started and finished:
            try:
                from datetime import datetime
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                finished_dt = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                duration = (finished_dt - started_dt).total_seconds()
            except (ValueError, AttributeError):
                pass
        if created and started:
            try:
                from datetime import datetime
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                queue_time = (started_dt - created_dt).total_seconds()
            except (ValueError, AttributeError):
                pass
        job_metrics.append({
            "job_id": job.get("job_id", ""),
            "subagent_id": job.get("subagent_id", ""),
            "status": job.get("status", ""),
            "duration_seconds": round(duration, 1) if duration else None,
            "queue_time_seconds": round(queue_time, 1) if queue_time else None,
        })

    # Calculate parallelism metrics
    completed_jobs = [j for j in job_metrics if j["duration_seconds"] is not None]
    total_job_time = sum(j["duration_seconds"] for j in completed_jobs) if completed_jobs else 0

    # Estimated sequential time = sum of all job durations
    # Actual parallel time = max(overlap-adjusted job times)
    # Simplified: use total run time and compare with sum of job times
    run_duration = summary.get("duration_seconds") if summary else None

    # Find max concurrent jobs (how many were running at the same time)
    # Use job timestamps to calculate overlap
    concurrent_periods = 0
    max_concurrent = 0
    if len(jobs) >= 2:
        finished_jobs = [j for j in jobs if j.get("started_at") and j.get("finished_at")]
        if len(finished_jobs) >= 2:
            from datetime import datetime
            intervals = []
            for j in finished_jobs:
                try:
                    s = datetime.fromisoformat(j["started_at"].replace("Z", "+00:00"))
                    e = datetime.fromisoformat(j["finished_at"].replace("Z", "+00:00"))
                    intervals.append((s.timestamp(), e.timestamp()))
                except (ValueError, AttributeError):
                    pass
            if intervals:
                min_start = min(i[0] for i in intervals)
                max_end = max(i[1] for i in intervals)
                # Count concurrent jobs at each job's start time
                for start, end in intervals:
                    concurrent = sum(1 for s, e in intervals if s <= start < e)
                    max_concurrent = max(max_concurrent, concurrent)

    # Subagent LLM call metrics
    subagent_llm_calls = [c for c in llm_calls if c.get("run_id") != run_dir.name]
    subagent_tokens = sum(
        (c.get("input_tokens", 0) or 0) + (c.get("output_tokens", 0) or 0)
        for c in subagent_llm_calls
    )

    main_llm_calls = [c for c in llm_calls if c.get("run_id") == run_dir.name]
    main_tokens = sum(
        (c.get("input_tokens", 0) or 0) + (c.get("output_tokens", 0) or 0)
        for c in main_llm_calls
    )

    speedup = round(total_job_time / max(run_duration, 1), 2) if run_duration and completed_jobs else None

    return {
        "run_id": run_dir.name,
        "has_subagents": True,
        "run_duration_seconds": run_duration,
        "total_jobs": len(jobs),
        "completed_jobs": len(completed_jobs),
        "total_job_cpu_time_seconds": round(total_job_time, 1),
        "estimated_sequential_time_seconds": round(total_job_time, 1),
        "speedup_vs_sequential": speedup,
        "time_saved_seconds": round(total_job_time - run_duration, 1) if run_duration else None,
        "time_saved_pct": (
            round((1 - run_duration / total_job_time) * 100, 1)
            if run_duration and total_job_time > 0 else None
        ),
        "max_concurrent_jobs": max_concurrent,
        "job_metrics": job_metrics,
        # Token breakdown
        "main_agent_tokens": main_tokens,
        "subagent_tokens": subagent_tokens,
        "total_tokens": main_tokens + subagent_tokens,
        "subagent_token_pct": round(subagent_tokens / (main_tokens + subagent_tokens) * 100, 1) if (main_tokens + subagent_tokens) > 0 else 0,
    }


# ---------------------------------------------------------------------------
# Comparison: compaction ON vs OFF
# ---------------------------------------------------------------------------

def compare_compaction(runs: list[dict]) -> dict:
    """Compare compaction-enabled vs disabled runs.

    Classifies runs by checking config.json for context_compaction_enabled.
    Falls back to checking if any L1/L4 compaction events exist.
    """
    enabled = []
    disabled = []
    for r in runs:
        run_dir = Path(r.get("run_dir", ""))
        config = _load_json(run_dir / "config.json") if run_dir.name else None
        if config and isinstance(config.get("config"), dict):
            if config["config"].get("context_compaction_enabled"):
                enabled.append(r)
            else:
                disabled.append(r)
        elif r.get("l1_tool_result_budget", {}).get("count", 0) > 0 or r.get("l4_auto_compactions", 0) > 0:
            enabled.append(r)
        else:
            disabled.append(r)

    def avg(metrics, key):
        vals = [m[key] for m in metrics if m.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    result = {
        "enabled_runs": len(enabled),
        "disabled_runs": len(disabled),
    }
    if enabled:
        l1_total = sum(r.get("l1_tool_result_budget", {}).get("count", 0) for r in enabled)
        result["with_compaction"] = {
            "avg_total_input_tokens": avg(enabled, "total_input_tokens"),
            "avg_steps": avg(enabled, "steps"),
            "avg_llm_calls": avg(enabled, "llm_call_count"),
            "avg_cache_hit_rate": avg(enabled, "overall_cache_hit_rate"),
            "avg_duration_seconds": avg(enabled, "duration_seconds"),
            "total_l1_budget_events": l1_total,
            "cache_hit_first_10": avg(enabled, "cache_hit_first_10"),
            "cache_hit_last_10": avg(enabled, "cache_hit_last_10"),
        }
    if disabled:
        result["without_compaction"] = {
            "avg_total_input_tokens": avg(disabled, "total_input_tokens"),
            "avg_steps": avg(disabled, "steps"),
            "avg_llm_calls": avg(disabled, "llm_call_count"),
            "avg_cache_hit_rate": avg(disabled, "overall_cache_hit_rate"),
            "avg_duration_seconds": avg(disabled, "duration_seconds"),
        }
    # Token savings from compaction
    if enabled and disabled:
        enabled_tokens = avg(enabled, "total_input_tokens")
        disabled_tokens = avg(disabled, "total_input_tokens")
        if enabled_tokens and disabled_tokens and disabled_tokens > 0:
            result["token_savings_pct"] = round((1 - enabled_tokens / disabled_tokens) * 100, 1)
    return result


def compare_parallelism(runs: list[dict]) -> dict:
    """Compare parallelism-enabled vs disabled runs."""
    with_par = [r for r in runs if r.get("has_subagents")]
    without_par = [r for r in runs if not r.get("has_subagents")]

    def avg(metrics, key):
        vals = [m[key] for m in metrics if m.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "with_parallelism_runs": len(with_par),
        "without_parallelism_runs": len(without_par),
        "with_parallelism": {
            "avg_duration_seconds": avg(with_par, "run_duration_seconds"),
            "avg_total_tokens": avg(with_par, "total_tokens"),
            "avg_speedup": avg(with_par, "speedup_vs_sequential"),
        } if with_par else None,
        "without_parallelism": {
            "avg_duration_seconds": avg(without_par, "run_duration_seconds"),
            "avg_total_tokens": avg(without_par, "total_tokens"),
        } if without_par else None,
    }


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_skill_report(data: dict) -> str:
    lines = [
        "=" * 72,
        "  SKILL TWO-STAGE LOADING: Token Reduction Analysis",
        "=" * 72,
        "",
        f"  Skills found: {data['total_skills']}",
    ]
    for s in data["skills"]:
        lines.append(
            f"    {s['name']:30s}  metadata: {s['metadata_chars']:>5d} chars  "
            f"body: {s['body_chars']:>5d} chars  "
            f"ratio: {s['ratio']:.1%}"
        )
    lines.extend([
        "",
        f"  One-stage (full body in prompt):   {data['one_stage_chars']:>6d} chars  ~{data['one_stage_estimated_tokens']:>6d} tokens",
        f"  Two-stage (metadata only):          {data['two_stage_chars']:>6d} chars  ~{data['two_stage_estimated_tokens']:>6d} tokens",
        f"  Saved:                              {data['saved_chars']:>6d} chars  ~{data['saved_estimated_tokens']:>6d} tokens  ({data['savings_pct']}%)",
        "",
        "  Impact: The two-stage loading defers skill instruction bodies until the",
        "  model explicitly activates a skill via the activate_skill tool. This keeps",
        "  the stable system prompt prefix smaller, improving prompt cache utilization.",
    ])
    return "\n".join(lines)


def format_compaction_report(metrics: dict) -> str:
    l1 = metrics.get("l1_tool_result_budget", {})
    lines = [
        "=" * 72,
        f"  CONTEXT COMPACTION: {metrics['run_id']}",
        "=" * 72,
        "",
        f"  Status:              {metrics['status']}",
        f"  Duration:            {metrics['duration_seconds']:.1f}s" if metrics.get('duration_seconds') else "",
        f"  Steps:               {metrics['steps']}",
        f"  LLM calls:           {metrics['llm_call_count']} ({metrics['successful_llm_calls']} primary, {metrics['failed_llm_calls']} retry)",
        f"  Tool calls:          {metrics['tool_call_count']}",
        "",
        f"  ── Compaction Pipeline ──",
        f"  L1 tool_result_budget:  {l1.get('count', 0)} events, ~{l1.get('estimated_tokens_saved', 0):,} tokens saved",
        f"  L4 auto_compact:        {metrics['l4_auto_compactions']} events",
        f"  Reactive compaction:    {metrics['reactive_compactions']} events",
        f"  Total compaction:       {metrics['compaction_events_total']} events",
        "",
    ]

    if metrics["auto_metrics"]:
        lines.append("  L4 Auto-compaction details:")
        for m in metrics["auto_metrics"]:
            status = "OK" if m["success"] else "FAIL"
            lines.append(
                f"    #{m['attempt']} [{status}]  "
                f"before: {m['before_tokens']:>8d}  →  after: {m['after_tokens']:>8d}  "
                f"reduction: {m['reduction_tokens']:>7d} tokens  "
                f"({m['reduction_pct']:.1f}%, ratio {m['compression_ratio']}:1)"
            )

    if metrics["reactive_metrics"]:
        lines.append("  Reactive-compaction details:")
        for m in metrics["reactive_metrics"]:
            status = "OK" if m["success"] else "FAIL"
            lines.append(
                f"    #{m['attempt']} [{status}]  "
                f"before: {m['before_tokens']:>8d}  →  after: {m['after_tokens']:>8d}  "
                f"reduction: {m['reduction_tokens']:>7d} tokens"
            )

    lines.extend([
        "",
        f"  ── Token Metrics ──",
        f"  Total input tokens:      {metrics['total_input_tokens']:>10,}",
        f"  Total output tokens:     {metrics['total_output_tokens']:>10,}",
        f"  Total cached tokens:     {metrics['total_cached_tokens']:>10,}",
        f"  Overall cache hit rate:  {metrics['overall_cache_hit_rate']:.1%}",
    ])

    if metrics.get("cache_hit_first_10") is not None:
        lines.append(f"  First 10 calls cache:    {metrics['cache_hit_first_10']:.1%}")
    if metrics.get("cache_hit_last_10") is not None:
        lines.append(f"  Last 10 calls cache:     {metrics['cache_hit_last_10']:.1%}")

    return "\n".join(lines)


def format_parallelism_report(metrics: dict) -> str:
    if not metrics.get("has_subagents"):
        return f"No background jobs in run {metrics['run_id']}"

    lines = [
        "=" * 72,
        f"  SUBAGENT PARALLELISM: {metrics['run_id']}",
        "=" * 72,
        "",
        f"  Run wall-clock time:      {metrics['run_duration_seconds']:.1f}s" if metrics['run_duration_seconds'] else "",
        f"  Total jobs:               {metrics['total_jobs']} ({metrics['completed_jobs']} completed)",
        f"  Sum of job CPU times:     {metrics['total_job_cpu_time_seconds']:.1f}s (estimated sequential)",
        f"  Max concurrent jobs:      {metrics['max_concurrent_jobs']}",
    ]

    if metrics["speedup_vs_sequential"] is not None:
        lines.append(f"  Speedup vs sequential:    {metrics['speedup_vs_sequential']}x")
    if metrics["time_saved_seconds"] is not None:
        lines.append(f"  Time saved:               {metrics['time_saved_seconds']:.1f}s ({metrics.get('time_saved_pct', 'N/A')}%)")

    lines.extend([
        "",
        "  Token breakdown:",
        f"    Main agent:             {metrics['main_agent_tokens']:>8d}",
        f"    Subagents:              {metrics['subagent_tokens']:>8d} ({metrics['subagent_token_pct']}%)",
        f"    Total:                  {metrics['total_tokens']:>8d}",
        "",
        "  Job details:",
    ])
    for j in metrics["job_metrics"]:
        dur = f"{j['duration_seconds']}s" if j["duration_seconds"] else "N/A"
        queue = f"{j['queue_time_seconds']}s queue" if j.get("queue_time_seconds") else ""
        lines.append(f"    {j['job_id']:12s}  {j['status']:15s}  duration: {dur:>8s}  {queue}")

    return "\n".join(lines)


def format_comparison_report(compaction_comp: dict, parallelism_comp: dict) -> str:
    lines = [
        "",
        "=" * 72,
        "  ABLATION COMPARISON SUMMARY",
        "=" * 72,
    ]

    if compaction_comp["with_compaction"] and compaction_comp["without_compaction"]:
        w = compaction_comp["with_compaction"]
        wo = compaction_comp["without_compaction"]
        token_saved_pct = (
            round((1 - w["avg_total_tokens"] / wo["avg_total_tokens"]) * 100, 1)
            if wo["avg_total_tokens"] and w["avg_total_tokens"] else None
        )
        lines.extend([
            "",
            "  ── Compaction ON vs OFF ──",
            f"    With compaction:    avg tokens={w['avg_total_tokens']}, steps={w['avg_steps']}, cache={w['avg_cache_hit_rate']}",
            f"    Without compaction: avg tokens={wo['avg_total_tokens']}, steps={wo['avg_steps']}, cache={wo['avg_cache_hit_rate']}",
        ])
        if token_saved_pct is not None:
            lines.append(f"    Token savings:      {token_saved_pct}% with compaction enabled")

    if parallelism_comp["with_parallelism"] and parallelism_comp["without_parallelism"]:
        wp = parallelism_comp["with_parallelism"]
        np = parallelism_comp["without_parallelism"]
        time_saved_pct = (
            round((1 - wp["avg_duration_seconds"] / np["avg_duration_seconds"]) * 100, 1)
            if np["avg_duration_seconds"] and wp["avg_duration_seconds"] else None
        )
        lines.extend([
            "",
            "  ── Subagent Parallelism ON vs OFF ──",
            f"    With parallelism:    avg time={wp['avg_duration_seconds']}s, tokens={wp['avg_total_tokens']}, speedup={wp['avg_speedup']}x",
            f"    Without parallelism: avg time={np['avg_duration_seconds']}s, tokens={np['avg_total_tokens']}",
        ])
        if time_saved_pct is not None:
            lines.append(f"    Time savings:        {time_saved_pct}% with parallelism enabled")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Analyze nanoAgent run artifacts")
    parser.add_argument("--run-dir", type=Path, help="Single run directory to analyze")
    parser.add_argument("--all-runs", action="store_true", help="Analyze all runs under .nano/runs/")
    parser.add_argument("--skill-only", action="store_true", help="Only run skill loading analysis")
    parser.add_argument("--compact-only", action="store_true", help="Only run compaction analysis")
    parser.add_argument("--parallel-only", action="store_true", help="Only run parallelism analysis")
    parser.add_argument("--runs-root", type=Path, default=Path(".nano/runs"), help="Runs root directory")
    args = parser.parse_args()

    run_all = not args.skill_only and not args.compact_only and not args.parallel_only

    # 1. Skill analysis (always runs if not explicitly excluded, since it's static)
    if run_all or args.skill_only:
        skill_data = analyze_skill_loading()
        print(format_skill_report(skill_data))

    # Collect runs if needed
    runs_root = args.runs_root
    run_dirs = []
    if args.run_dir:
        run_dirs = [args.run_dir]
    elif args.all_runs:
        if runs_root.exists():
            run_dirs = sorted(runs_root.iterdir(), key=lambda p: p.name)
            run_dirs = [d for d in run_dirs if d.is_dir() and (d / "summary.json").exists()]

    # 2. Compaction analysis
    if run_all or args.compact_only:
        if not run_dirs:
            print("\n[compaction] No run directories specified. Use --run-dir or --all-runs.")
        compaction_results = []
        for run_dir in run_dirs:
            metrics = analyze_compaction(run_dir)
            compaction_results.append(metrics)
            print("\n" + format_compaction_report(metrics))

        if len(compaction_results) >= 2:
            comp = compare_compaction(compaction_results)
            # Will print in combined summary below

    # 3. Parallelism analysis
    if run_all or args.parallel_only:
        if not run_dirs:
            print("\n[parallelism] No run directories specified. Use --run-dir or --all-runs.")
        parallelism_results = []
        for run_dir in run_dirs:
            metrics = analyze_parallelism(run_dir)
            parallelism_results.append(metrics)
            print("\n" + format_parallelism_report(metrics))

    # 4. Combined comparison summary
    if len(run_dirs) >= 2:
        compaction_comp = compare_compaction([
            analyze_compaction(d) for d in run_dirs
        ])
        parallelism_comp = compare_parallelism([
            analyze_parallelism(d) for d in run_dirs
        ])
        print(format_comparison_report(compaction_comp, parallelism_comp))


if __name__ == "__main__":
    main()
