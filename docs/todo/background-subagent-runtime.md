# Background Subagent Runtime Follow-ups

This note records development issues exposed by the Django repository stress run
and the intended semantics for querying background subagent jobs.

## Source Run

- Run directory: `.nano/runs/20260701142942`
- Repository: `https://github.com/django/django`
- Scenario: main agent delegated ORM, URL resolver, and test runner analysis to
  three background subagents.

The run completed, but it exposed runtime and prompt issues around background
waiting, result delivery, finalization, and cache stability.

## Desired Query Semantics

Background subagent tools should separate four different actions:

- `delegated_task_list`: inspect job status only.
- `delegated_task_get`: inspect one specific job when more detail is needed.
- `delegated_task_wait`: explicitly wait for background progress with a bounded timeout.
- background completion hook: automatically deliver newly completed job results.

The main path should be:

1. The main agent starts background jobs.
2. The main agent continues useful foreground work if any exists.
3. If no useful foreground work remains, the main agent calls `delegated_task_wait`.
4. When jobs finish, completion results are delivered once through wait or hook injection.
5. The main agent uses `task_get` or `delegated_task_get` only when the delivered result is
   missing required evidence.

Repeated `delegated_task_list` polling should not be the normal waiting mechanism.

## Tool Behavior Contract

### `delegated_task_list`

Default behavior is lightweight:

- Return `job_id`, `task_id`, `subagent_id`, `status`, timestamps, and elapsed time.
- Do not return full terminal results by default.
- Do not consume completion events by default.
- Allow a bounded `include_results=true` mode only when explicitly needed.
- `include_results=true` marks returned terminal results as delivered.

### `delegated_task_get`

`get` still has a purpose, but it should not be the main completion path.

Valid uses:

- Check one job's current status.
- Recover a result if hook/wait delivery was missed or compacted.
- Fetch bounded details for one known job.
- Answer a user request about one specific job.

If the job is still running, `get` returns a running snapshot with `result=null` and should
not mark the job observed.

If the job is terminal:

- If the result has not been delivered, return a bounded result and mark it observed.
- If the result was already delivered, return an `already_delivered` summary by default.
- Full result re-fetch requires `include_result=true`.

### `delegated_task_wait`

Implemented as a dedicated wait tool instead of overloading list.

Suggested input:

```json
{
  "timeout_seconds": 30,
  "job_ids": ["job-1", "job-2"],
  "return_when": "any_completed"
}
```

Suggested behavior:

- Clamp timeout to a safe range, for example `1..background_idle_wait_timeout_seconds`.
- Return newly completed jobs and compact result summaries.
- Return active job status summaries on timeout.
- Mark only returned terminal results as observed.
- Do not repeat already delivered terminal results.

Current implementation:

- `timeout_seconds` is capped by `background_idle_wait_timeout_seconds`.
- `job_ids` can restrict which jobs the wait consumes.
- `completed_jobs` contains newly delivered terminal results.
- `active_jobs` contains lightweight active job status without result payloads.
- Completion events returned by wait are marked observed, so the background completion hook does
  not inject the same result again.

This gives the LLM an explicit alternative to polling:

```text
If useful foreground work remains, continue it.
If no useful foreground work remains, call delegated_task_wait with a bounded timeout.
Do not repeatedly call delegated_task_list only to wait.
```

## Observed Runtime Issues

### 1. `delegated_task_list` caused repeated large result injection

The main agent repeatedly called `delegated_task_list` while jobs were running. After jobs
started completing, list returned full results for terminal jobs multiple times.

Observed message sizes:

- `background_job_updates` for job-1: about 12.6k characters.
- `delegated_task_list` with one completed result: about 13.2k characters.
- `delegated_task_list` with two completed results: about 29.1k characters.
- `delegated_task_list` with three completed results: about 35.4k characters.

Impact:

- Main context grew quickly.
- Prompt cache hit rate became unstable.
- The same subagent reports appeared through both hook injection and list results.

### 2. Main-agent cache instability was driven by result delivery, not summary compaction

The source run had no `compactions.jsonl` and no persisted `tool-results/` artifacts, so
LLM summary compaction was not the cause of cache drops.

Main-agent cache examples:

- `llm-5`: about 5.6 percent cache hit.
- `llm-10`: about 4.7 percent cache hit.
- `llm-11` to `llm-15`: about 5.8 to 16.7 percent.
- `llm-16`: about 86.1 percent.
- `llm-17`: about 91.2 percent.

Likely causes:

- Large `list_files` outputs early in the run.
- Active skill injection.
- Repeated background result delivery through both hooks and list.
- Tool/result message changes rather than LLM-backed compaction.

### 3. Finalization step produced duplicate `llm_call_id`

Subagents use `reserve_final_step=True`. At finalization, available tools are reduced to
`finish_run` only.

In subagent-1 and subagent-3:

- The finalization call used `llm-30`.
- The correction call also used `llm-30`.
- Both calls had `available_tool_count=1`.
- Both calls had `cached_tokens=0`.

Impact:

- `llm_call_id` is not unique for finalization correction.
- Metrics and message tracing become ambiguous.
- Cache loss is explainable because the tool schema changes, but the duplicate id is a bug.

Required fix:

- Give finalization correction a distinct attempt type/id, for example
  `llm-30-finalization-correction-1`.

### 4. Finalization prompt was not strict enough

At reserved finalization, subagent-1 and subagent-3 were told to call `finish_run` only, but
both still requested a file tool. Runtime correctly returned `finalization_tool_denied`, then
issued a correction prompt.

Impact:

- One extra LLM call per affected subagent.
- The extra finalization/correction call lost cache.
- The agent wasted part of the reserved finalization path.

Possible fixes:

- Strengthen finalization prompt wording.
- Consider exposing only `finish_run` earlier when the step budget is nearly exhausted.
- Add tests for finalization invalid tool calls and unique LLM call ids.

### 5. Continuation after `max_tokens` is too expensive

Subagent-2 hit `max_tokens` at `llm-23`:

- Output tokens reached `32768`.
- The truncated assistant message was appended to the context.
- Continuation request `llm-23-continuation-1` had `cached_tokens=0`.
- The continuation then called another `read_file` before finishing.

Current behavior is protocol-valid, but expensive.

Potential fixes:

- Compact or truncate the previous assistant content before continuation.
- For max-token continuations near final report generation, encourage concise completion or
  `finish_run`.
- Prevent continuation from launching unrelated new investigation.

### 6. Background allowed-tools error message is misleading

When the main agent passed disallowed `allowed_tools`, the error message said:

```text
Background subagents can use only read-only filesystem tools: run_command
```

The listed name is actually the denied tool, not the allowed tool. This misled the model into
trying `run_command` only, causing another failed delegation round.

Required fix:

- Report denied tools and allowed tools separately.
- Example:

```text
Background subagents cannot use these tools: run_command.
Allowed background tools are: grep, list_files, read_file.
Omit allowed_tools to use the default read-only set.
```

## Suggested Development Order

Completed:

- Fixed the background allowed-tools error message.
- Made finalization correction LLM call ids unique.
- Added `delegated_task_wait` with bounded timeout.
- Made `delegated_task_list` status-only by default.
- Refined delivered-result semantics across hook injection, wait, list, and get.
- Tightened continuation prompts while keeping one unified `max_tokens` recovery limit.

Remaining:

1. Re-run the Django stress scenario and compare cache hit rate, message growth, and repeated
   background result delivery.
