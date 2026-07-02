# Background Subagent Runtime

Background subagents let the main Agent delegate independent, read-heavy work while it keeps useful foreground work available.

## Completed Runtime Semantics

- `delegate_task(run_in_background=true, task_id=...)` creates a background Job and lets the runtime own the linked Task status.
- `delegated_task_wait` is the normal waiting mechanism when no useful foreground work remains.
- `delegated_task_list` is status-only by default and does not consume terminal results.
- `delegated_task_get` returns one terminal result once by default; already delivered results require `include_result=true`.
- Completion hook injection and `delegated_task_wait` both mark delivered terminal results so the same Job result is not injected twice.
- `delegated_task_wait(job_ids=...)` only consumes matching completion events.

## Result Payloads

Subagent persistence keeps the complete `completion_report`. Successful subagents no longer duplicate `completion_report.resolution` into `output`; `output` is only a fallback when no completion report exists.

LLM-facing background results return `completion_report` without `output` when a report exists. If result payloads must be compacted, the response includes a `full_result` artifact reference such as:

```text
subagents/subagent-1/result.json
```

## Observed Improvements

The Django stress rerun `.nano/runs/20260702033441` improved over `.nano/runs/20260701142942`:

- duration: `335.4s` to `219.4s`
- LLM calls: `17` to `14`
- tool failures: `6` to `0`
- weighted cache hit rate: about `0.50` to `0.84`
- repeated `delegated_task_list` result injection was eliminated

## Remaining Work

Open follow-ups are tracked in `docs/todo/`.
