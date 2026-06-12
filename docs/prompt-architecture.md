# Prompt Architecture

## Goals

The MVP prompt layer separates stable operating policy from task-specific state:

1. Keep the core system prefix stable for provider-side prefix caching.
2. Pass tool schemas through the model API instead of duplicating them in prompt text.
3. Inject skills, memory, and runtime context only when relevant.
4. Keep conversation updates append-only for recovery and cache reuse.
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

During the run, `PromptContextHook` appends:

- a context update after repository state or tool evidence materially changes.

It does not rewrite earlier messages and does not inject an update for step-number changes
alone.

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

`RunContextBuilder` derives a bounded snapshot from persisted protocol messages. It retains:

- clone state;
- inspected files;
- modified files;
- commands;
- recent tool success or failure summaries.

Raw tool output remains in the message stream. The context snapshot avoids copying full logs
into repeated prompt updates.

## Current limits

- The model selects skills from metadata without semantic retrieval or ranking.
- Skill references, scripts, and assets are not loaded yet.
- Memory retrieval uses metadata filters rather than embeddings.
- Context compression is structural and does not summarize arbitrary long file content.
- Prompt instructions define completion criteria, but the runtime still maps any model
  `end_turn` response to a successful run. A later protocol revision should add explicit
  completed, blocked, and failed outcomes.
- Cache behavior depends on the configured OpenAI-compatible provider and model.
