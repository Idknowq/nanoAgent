# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`nanoAgent` — a lightweight AI Agent prototype for repository diagnosis and small-scope code repair. The core execution model is a Claude Code-style tool-use loop: send context to LLM, call tools on `tool_use`, inject results back, repeat until `end_turn` or `finish_run`.

## Architecture

### Entry Point & Wiring

`NanoAgent` (`nano_agent/agent.py`) is the top-level entry point. It creates the workspace, builds the tool registry, hook chain, subagent manager, prompt, compactor, and launches `AgentLoop`. It does NOT define the loop logic itself — it wires components together.

### Core Loop (`nano_agent/loop.py`)

`AgentLoop.run()` is the heart of the system. Each iteration:
1. Optionally runs `ContextCompactor.prepare()` to reduce context size before the LLM call.
2. Calls `llm.complete(messages, tools)` with full recovery logic (`_call_llm_with_recovery`):
   - Transient errors (rate-limit, overload, timeout, connection) → bounded exponential backoff with jitter.
   - `max_tokens` (truncated output) → up to N continuation requests; partial tool-call JSON is never joined.
   - `prompt_too_long` → one reactive compaction retry.
   - `invalid_response` → one regeneration prompt; invalid tool JSON is never repaired in place.
3. Executes any tool calls, runs hooks before/after each, validates `finish_run` protocol.
4. Appends results to message history and continues.

### Tools (`nano_agent/tools/`)

`RuntimeTool` is the base class (ABC). Each tool has class-level `name`, `description`, `approval_level`, `input_schema`. Tools register via module-level `register_tool_factory()` calls; `build_default_tool_registry()` imports all built-in tool modules and constructs the registry.

`ToolRegistry` supports `register()`, `replace()`, `get()`, `selected()` (subsets by name). `ToolContext` carries per-invocation state (run_id, workspace_path, current_step, LLM call metadata, etc.).

Built-in tools: `clone_repo`, `list_files`, `grep`, `read_file`, `edit_file`, `run_command`, `finish_run`, `todo_write`, `activate_kill`, `delegate_task` (+ query/cancel variants), `task_create`/`task_get`/`task_list`/`task_update`.

### LLM Services (`nano_agent/services/`)

- `LLMClient` is a `Protocol` — any client implementing `complete(messages, tools) -> LLMResponse` works.
- `OpenAICompatibleLLMClient` handles DeepSeek via the OpenAI SDK. Provider registration uses a module-level registry (`register_llm_provider` / `create_llm_client`).
- `normalize_llm_error()` classifies SDK exceptions into `LLMErrorKind` enum with `retryable` property.
- `RetryPolicy` computes exponential backoff with jitter; respects `Retry-After` headers when present.

### Hooks (`nano_agent/hooks/`)

`AgentHook` protocol with 5 callbacks: `before_llm_call`, `after_llm_call`, `before_tool_call`, `after_tool_call`, `on_error`. Hooks can inject system messages into the conversation.

Default chain: `PermissionHook` → (optional) `ConsoleProgressHook` → (optional) `LLMMetricsHook` → (optional) `AuditHook`. `SkillActivationHook` is inserted at position 0 when skills are enabled.

### Context Compaction (`nano_agent/context/`)

`ContextCompactor.prepare()` runs this ordered pipeline before each LLM call:
1. **tool_result_budget** — persist the largest tool results from the latest batch to disk, replace with compact references.
2. **snip_compact** — when estimated tokens approach context limit, drop middle messages while preserving assistant-tool protocol boundaries.
3. **micro_compact** — replace older large tool results with a compact placeholder.
4. **auto_compact** (LLM summary) — ask the LLM to generate a conversation summary; runs at most 3 times per run.
5. **reactive_compact** — triggered by `prompt_too_long` error; keeps stable prefix + recent tail; runs at most once.

Token estimation uses a conservative 3 chars/token ratio, not a provider tokenizer. Persisted outputs go to `.nano-agent/tool-results/` in the workspace (after clone) or `run_dir/tool-results/` (before clone).

### Subagents & Background Jobs (`nano_agent/subagents/`, `nano_agent/background/`)

`SubagentManager` creates isolated one-level child `AgentLoop` instances. Children receive only the delegated task + explicit context; they cannot create further subagents. They can use only a reconstructible subset of parent tools.

`BackgroundJobSupervisor` wraps subagents in a `ThreadPoolExecutor` with bounded concurrency (default max 2). Jobs progress through states (queued → running → succeeded/blocked/failed/cancelled). Completion events are delivered to the parent conversation. Cancellation is cooperative at loop boundaries. The main Agent idles briefly waiting for active jobs before finishing.

### Tasks (`nano_agent/tasks/`)

Persistent task tracking with `PENDING → IN_PROGRESS → COMPLETED/BLOCKED/FAILED/CANCELLED` lifecycle. `blocked_by` dependencies auto-unblock when prerequisites complete. Background jobs can link to tasks and update their status automatically.

### Prompt Assembly (`nano_agent/prompts/`)

`PromptAssembler` builds the initial conversation from:
1. Stable core system prompt (`templates/core.md`) — designed for provider-side prefix caching.
2. Available skill metadata catalog (sorted, metadata only).
3. Retrieved memory records (filtered by repo tags).
4. User task message (formatted via `templates/repository_design.md`).

The core prompt hash is saved for reproducibility. Skills are NOT loaded into the initial prompt — only metadata. The model activates skills lazily via `activate_skill`.

### Skills (`nano_agent/skills/`)

Built-in skills in `skills/builtin/<name>/SKILL.md` use YAML frontmatter with `name` and `description`. Built-in: `python-repository`, `node-repository`, `django-repository`, `github-actions`.

### Runtime Isolation (`nano_agent/runtime/`)

`ExecutionEnvironmentManager` creates per-run isolated directories (`HOME`, `TMPDIR`, pip cache, npm prefix, cargo home, GOPATH, XDG dirs). Python tools (`python`, `python3`, `pytest`, `ruff`, `pip`) resolve from a run-scoped venv created via `python -m venv`. The active nanoAgent venv is excluded from `PATH` to prevent leakage.

### Run Lifecycle

- Run IDs are UTC timestamps (`YYYYMMDDHHMMSS`).
- Workspaces: `.nano/workspaces/<reponame>-<run_id>/`
- Artifacts: `.nano/runs/<run_id>/` — contains `summary.json`, `messages.jsonl`, `prompt.json`, `report.md`, `tasks/`, `subagents/`, `tool-results/`, `transcripts/`, `compactions.jsonl`, optional `context_checkpoint.json`, `llm_calls.jsonl`, `audit.jsonl`.
- Runs terminate via `finish_run` tool producing a `CompletionReport` (status: completed/blocked/failed, problem, root_cause, resolution, changed_files, verification_summary, remaining_risks, blockers). This renders to `report.md`.

### Data Models (`nano_agent/models.py`)

Central Pydantic models: `RunStatus`, `LLMStopReason`, `ApprovalLevel`, `AgentMessage`, `LLMResponse`, `LLMUsage`, `CompletionReport`, `RunSummary`, `ToolCallRecord`, `ToolUseRequest`.

### Config (`nano_agent/config.py`)

`AgentConfig` is a single Pydantic model with all runtime parameters. It has no file-based config — defaults are in the model field definitions, overridden via CLI flags or programmatic construction.

## Testing Patterns

Tests use pytest with `tmp_path` fixtures. Mock LLM clients (e.g., `OneToolUseLLM`, `ScriptedMvpLLMClient`) simulate deterministic model responses. `ScriptedMvpLLMClient` in `services/llm.py` can also be used for integration-style loop tests without API calls. Key test files mirror source module structure.
