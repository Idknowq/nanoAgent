# Prompt Architecture

## Goals

The MVP prompt layer separates stable operating policy from task-specific state:

1. Keep the core system prefix stable for provider-side prefix caching.
2. Pass tool schemas through the model API instead of duplicating them in prompt text.
3. Inject skills, memory, and runtime context only when relevant.
4. Keep the raw conversation append-only for recovery while compacting only the active context.
5. Persist prompt composition metadata for debugging and reproducibility.

## Message order

The initial conversation is assembled in this order:

1. Stable core system prompt from `nano_agent/prompts/templates/core.md`.
2. Available skill metadata catalog, sorted by skill name.
3. Retrieved memory, sorted by namespace and key.
4. Initial structured runtime context.
5. User task message.

The core prompt contains no run id, timestamp, repository URL, step counter, tool list, or
other per-run values. Its SHA-256 hash is saved in `prompt.json`.

The runtime does not append a new runtime-context system message on every LLM call. Tool
results already carry current evidence, while `RunContextBuilder` derives bounded state only
when an automatic compact summary needs it. This avoids invalidating the stable prompt prefix
for step-number-only changes.

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

The model calls `activate_skill` with a catalog name when the skill is relevant. The tool
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

## Runtime context

`RunContextBuilder` derives bounded durable state from protocol messages for the initial
snapshot and automatic compact summaries. It retains:

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
   under `tool-results/`, and replace them only when the reference is smaller.
2. `snip_compact`: when message count exceeds the configured threshold, keep the stable head
   and recent tail while preserving assistant-tool protocol boundaries.
3. `micro_compact`: replace older oversized tool results with
   `[Earlier tool result compacted. Re-run if needed.]`.
4. `compact_history`: if estimated input tokens still exceed the threshold, save a transcript
   and ask the LLM for a continuation summary. It may run at most three times per run.
5. `reactive_compact`: after a provider prompt-too-long error, retain the stable prefix and
   recent messages, then retry the main LLM request once.

`context_checkpoint.json` stores the latest active context. `messages.jsonl` remains the raw
append-only source of truth. `transcripts/`, `tool-results/`, and `compactions.jsonl` are
created when their corresponding mechanisms run.

## Current limits

- The model selects skills from metadata without semantic retrieval or ranking.
- Skill references, scripts, and assets are not loaded yet.
- Memory retrieval uses metadata filters rather than embeddings.
- Token estimation uses a conservative character ratio rather than provider tokenizers.
- Compact summaries use the same configured LLM client as the main Agent loop.
- Prompt instructions define completion criteria, but the runtime still maps any model
  `end_turn` response to a successful run. A later protocol revision should add explicit
  completed, blocked, and failed outcomes.
- Cache behavior depends on the configured OpenAI-compatible provider and model.
