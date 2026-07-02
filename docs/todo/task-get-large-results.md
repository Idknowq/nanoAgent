# `task_get` Large Result Injection

## Problem

After background results were delivered through `delegated_task_wait`, the main Agent still called `task_get` for completed linked Tasks. `task_get` returned full Task results and reintroduced large subagent reports into the main context.

## Cause

- Background Job delivery now has delivered-result semantics, but Task queries do not.
- `task_get` defaults to returning the full `TaskRecord`, including `result`.
- Linked Tasks store the subagent report as `task.result`, so completed Task reads can duplicate already delivered Job results.

## Fix Plan

- Add `include_result: bool = False` to `task_get`.
- Default `task_get` to status-only fields: `task_id`, `subject`, `status`, `owner`, dependencies, timestamps, and error summary.
- Return `result` only when `include_result=true`.
- For Tasks managed by background Jobs, include a lightweight pointer to the owning Job so the main Agent can use `delegated_task_get` or result artifacts intentionally.
- Update prompts to prefer `delegated_task_wait` results over `task_get` for completed background work.

## Acceptance Criteria

- Default `task_get` no longer injects large completed results.
- Existing callers can still retrieve full results explicitly with `include_result=true`.
- Re-running the Django scenario does not show repeated full reports from both Job delivery and Task reads.
