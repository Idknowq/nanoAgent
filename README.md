# nanoAgent

`nanoAgent` is a lightweight AI Agent prototype for repository diagnosis and small-scope code repair.

Current phase: guarded tool-use loops with run persistence, cache-oriented prompt composition,
and bounded one-level subagent delegation.

Planned MVP loop:

1. Send the user request and current context to the LLM.
2. If the LLM returns `tool_use`, call the requested tool.
3. Append the tool result back into the message history.
4. Continue the loop until the LLM returns `end_turn`.
5. Keep `todo_write` as an optional short-lived session planning tool.
6. Use structured `run_command` execution only when a dedicated tool is insufficient.

Prompt assembly uses a stable Markdown core plus selective skill and memory injection. See
[docs/prompt-architecture.md](docs/prompt-architecture.md).

The active conversation is bounded by tool-result persistence, structural trimming,
micro-compaction, LLM-generated summaries, and a one-shot prompt-too-long fallback. The raw
protocol stream remains available in each run's `messages.jsonl`.

LLM requests normalize provider stop reasons and errors. Transient rate-limit, overload,
timeout, and connection failures use bounded exponential backoff with jitter. Output-limit
responses request bounded continuation, while prompt-too-long failures receive one reactive
compaction retry and then fail without further emergency compaction.

Runs terminate through the structured `finish_run` tool. The validated user-facing result is
written to `.nano/runs/<run_id>/report.md`; the terminal prints only concise progress and the
report path, not the report body or full run summary.

The main Agent can call `delegate_task` to run one scoped task in a child `AgentLoop`. A child
receives only the delegated task and explicit context, has independent messages, counters,
compaction state, hooks, and persistence, and can use only a reconstructible subset of the
parent's tools. Child lifecycle and results are stored under
`.nano/runs/<run_id>/subagents/<subagent_id>/`.

Delegation can run synchronously or as a background Job. Background Jobs use a bounded
in-process supervisor, default to at most two concurrent read-only subagents, and expose
`delegated_task_get`, `delegated_task_list`, and `delegated_task_cancel`. Terminal results are
injected into the parent conversation once. When the main Agent tries to finish while Jobs
remain active, the runtime waits briefly for any Job to complete before the next model turn.
Cancellation is cooperative at Agent loop boundaries; an already-running LLM request or tool
call is allowed to return before the child stops. Recursive delegation, concurrent child
writes, process-restart recovery, and distributed scheduling are not implemented.

The main Agent also has persistent `task_create`, `task_get`, `task_list`, and `task_update`
tools. Tasks are stored under `.nano/runs/<run_id>/tasks/`, support validated lifecycle
transitions and `blocked_by` dependencies, and automatically unblock dependency-blocked tasks
when all prerequisites complete. This task state is distinct from the short-lived `todo_write`
checklist. A background Job may reference one Task and automatically update its execution
status. Cancelling one Job returns an in-progress Task to `pending`; it does not cancel the
Task itself.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## CLI

```bash
nano-agent run https://github.com/example/repo \
  "Inspect the repository, repair verified defects, and run relevant tests."
```

During early development, use:

```bash
python -m nano_agent.cli run https://github.com/example/repo \
  "Inspect the repository, repair verified defects, and run relevant tests."
```

Set `--background-idle-wait-timeout` to control how long the runtime waits for any
background Job when no foreground progress is available. The default is 30 seconds.
