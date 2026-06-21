# Prompt Architecture

## Goals

The MVP prompt layer separates stable operating policy from task-specific state:

1. Keep the core system prefix stable for provider-side prefix caching.
2. Pass tool schemas through the model API instead of duplicating them in prompt text.
3. Inject skills and memory only when relevant.
4. Keep the raw conversation append-only for recovery while compacting only the active context.
5. Persist prompt composition metadata for debugging and reproducibility.
6. Keep optional mechanisms such as Tasks, delegation, and skills benefit-driven rather than
   mandatory steps.

## Message order

The initial conversation is assembled in this order:

1. Stable core system prompt from `nano_agent/prompts/templates/core.md`.
2. Available skill metadata catalog, sorted by skill name.
3. Retrieved memory, sorted by namespace and key.
4. User task message.

The core prompt contains no run id, timestamp, repository URL, step counter, tool list, or
other per-run values. Its SHA-256 hash is saved in `prompt.json`.

## Skills

Built-in skills use the Agent Skills directory format:

```text
skills/builtin/
  python-repository/
    SKILL.md
```

Each `SKILL.md` starts with YAML frontmatter containing at least `name` and `description`.
Startup discovery reads and validates only this metadata. The body is not loaded into the
initial prompt.

The model calls `activate_skill` with a catalog name when specialized procedural guidance will
materially improve the task. Activation is optional and should happen before deep domain work. The tool
loads the body, returns only activation metadata, and `SkillActivationHook` appends the body
as a bounded system message after the tool result. A skill is loaded and injected at most
once per run.

Optional `allowed-tools` metadata is descriptive only. It does not grant permission or
change the active tool registry.

`AgentConfig.skills_root` can point to an alternative directory of skill folders. Skills
cannot override core safety or permission rules.

## Memory

`JsonlMemoryStore` supports append-only records and deterministic filtering by namespace
and tags. Set `AgentConfig.memory_path` to enable initial memory retrieval.

Repository, failure, and run memories must match the repository URL or repository-name tag.
Global `user_preference` records may be loaded without repository tags. Memory is treated as
reference data, not as authoritative instructions.

## Compaction state

`CompactionStateBuilder` derives bounded durable state only when an automatic compact summary
needs it. It retains:

- clone state;
- inspected files;
- modified files;
- successful commands;
- uniquely identified tool failures for incremental comparison.

Raw messages remain in `messages.jsonl`; the active request context may contain persisted
result references, placeholders, or a generated conversation summary.

## Context compaction

Before each main LLM request, `ContextCompactor` applies this ordered pipeline:

1. `tool_result_budget`: inspect the latest tool-result batch, persist the largest results
   under `.nano-agent/tool-results/` in the workspace, and replace them only when the
   workspace-relative reference is smaller. The replacement keeps a preview and a path that
   can be read with `read_file` if exact content is needed.
2. `snip_compact`: when estimated input tokens approach the usable context limit, keep the stable
   head and recent tail while preserving assistant-tool protocol boundaries. The default threshold
   leaves automatic summarization as the normal compaction path rather than deleting history early.
3. `micro_compact`: replace older oversized tool results with
   `[Earlier tool result compacted. Re-run if needed.]`.
4. `compact_history`: if estimated input tokens still exceed the threshold, save a transcript
   and ask the LLM for a continuation summary. It may run at most three times per run.
5. `reactive_compact`: after a provider prompt-too-long error, retain the stable prefix and
   recent messages, then retry the main LLM request once.

If reactive compaction does not reduce the estimated request size, the retry is skipped. If
the provider still reports prompt-too-long after the one reactive retry, the run fails; there
is no emergency compaction stage.

`context_checkpoint.json` stores the latest active context. `messages.jsonl` remains the raw
append-only source of truth. `transcripts/`, `tool-results/`, and `compactions.jsonl` are
created when their corresponding mechanisms run.

## LLM request recovery

Provider finish reasons are normalized as `tool_use`, `end_turn`, `max_tokens`,
`content_filter`, or `unknown`. A `max_tokens` response is persisted as partial assistant
output and followed by a bounded continuation request. Partial tool-call JSON is never joined;
the model must regenerate the complete tool call.

Rate-limit, overload, timeout, and connection failures retry within the same Agent step using
bounded exponential backoff and jitter, with `Retry-After` taking precedence when available.
Authentication, invalid-request, invalid-response, and unknown failures are not retried.
Every physical request has its own LLM call id and metrics record with its recovery type.

## Completion protocol

The model must finish through a single `finish_run` tool call. A plain `end_turn` receives
one correction message; a second plain `end_turn` fails the run.

The structured report declares `completed`, `blocked`, or `failed`. In the MVP, the runtime
validates the report structure and requires `finish_run` to be the only tool call in its LLM
response. Verification details and changed files are recorded from the model's report without
additional evidence validation.

Every run writes a uniform `report.md` containing the status, problem, root cause,
resolution, changed files, verification summary, remaining risks, blockers, and run
statistics. `summary.json` remains the machine-readable run index.

## Current limits

- The model selects skills from metadata without semantic retrieval or ranking.
- Skill references, scripts, and assets are not loaded yet.
- Memory retrieval uses metadata filters rather than embeddings.
- Token estimation uses a conservative character ratio rather than provider tokenizers.
- Compact summaries use the same configured LLM client as the main Agent loop.
- Cache behavior depends on the configured OpenAI-compatible provider and model.
