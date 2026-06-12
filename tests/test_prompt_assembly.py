import json
from pathlib import Path

import pytest

from nano_agent.config import AgentConfig
from nano_agent.context.snapshot import RunContextBuilder, RunContextSnapshot
from nano_agent.hooks.skill_activation import SkillActivationHook
from nano_agent.loop import AgentLoop
from nano_agent.memory.store import JsonlMemoryStore, MemoryRecord
from nano_agent.models import AgentMessage, LLMResponse, RunSummary, ToolUseRequest
from nano_agent.persistence.skill_activation_store import SkillActivationStore
from nano_agent.prompts.assembler import PromptAssembler, PromptRequest
from nano_agent.skills.registry import SkillFormatError, SkillParser, SkillRegistry
from nano_agent.skills.session import SkillSession
from nano_agent.tools.activate_skill import ActivateSkillTool
from nano_agent.tools.base import ToolContext, ToolRegistry


def write_skill(
    root: Path,
    name: str,
    *,
    description: str = "Diagnose Python failures.",
    content: str = "# Instructions\nRun the narrowest failing test.",
    metadata_name: str | None = None,
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        (
            "---\n"
            f"name: {metadata_name or name}\n"
            f"description: {description}\n"
            "metadata:\n"
            '  version: "1.0"\n'
            "---\n\n"
            f"{content}\n"
        ),
        encoding="utf-8",
    )
    return path


class ActivateThenFinishLLM:
    """Activate one skill, then verify its body is visible on the next call."""

    def __init__(self) -> None:
        self.calls = 0  # 记录测试 LLM 已完成的调用次数。
        self.second_call_messages: list[AgentMessage] = []  # 第二轮收到的完整消息。

    def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="load skill",
                stop_reason="tool_use",
                tool_uses=[
                    ToolUseRequest(
                        id="skill-1",
                        name="activate_skill",
                        input={"name": "python-repository"},
                    )
                ],
            )
        self.second_call_messages = list(messages)
        return LLMResponse(content="done", stop_reason="end_turn")


def test_prompt_assembler_keeps_stable_core_and_exposes_only_skill_metadata(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skills"
    body = "SECRET FULL SKILL BODY"
    write_skill(skill_root, "python-repository", content=body)
    metadata = SkillRegistry(skill_root).list_metadata()
    request = PromptRequest(
        user_request="Fix the failing tests.",
        repo_url="https://example.com/repo.git",
        context=RunContextSnapshot(repo_url="https://example.com/repo.git", max_steps=20),
        available_skills=metadata,
    )

    first = PromptAssembler().assemble(request)
    second = PromptAssembler().assemble(request)
    catalog = next(message for message in first.messages if "<available_skills>" in message.content)

    assert first.messages[0].role == "system"
    assert first.core_sha256 == second.core_sha256
    assert first.included_sections == ["core", "skill_catalog", "context", "task"]
    assert first.available_skill_names == ["python-repository"]
    assert "Diagnose Python failures." in catalog.content
    assert body not in "\n".join(message.content for message in first.messages)


def test_prompt_assembler_selectively_injects_memory(tmp_path: Path) -> None:
    store = JsonlMemoryStore(tmp_path / "memory.jsonl")
    matching = MemoryRecord(
        namespace="repo",
        key="test-command",
        value="Use pytest -q.",
        tags=["repo"],
    )
    store.add(matching)

    bundle = PromptAssembler().assemble(
        PromptRequest(
            user_request="Inspect.",
            repo_url="https://example.com/repo.git",
            context=RunContextSnapshot(repo_url="https://example.com/repo.git"),
            memories=store.search("repo", tags={"repo"}),
        )
    )

    memory_message = next(message for message in bundle.messages if "<retrieved_memory>" in message.content)
    assert "Use pytest -q." in memory_message.content
    assert bundle.memory_keys == ["repo:test-command"]


def test_skill_registry_parses_metadata_without_loading_body(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    path = write_skill(skill_root, "python-repository")
    parser = SkillParser()

    descriptor = parser.parse_metadata(path, skill_root)
    loaded = parser.load_content(descriptor)

    assert descriptor.metadata.name == "python-repository"
    assert descriptor.metadata.metadata == {"version": "1.0"}
    assert descriptor.content_offset > 0
    assert loaded.content.startswith("# Instructions")
    assert loaded.content_sha256


def test_skill_registry_rejects_invalid_frontmatter_and_name_mismatch(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    invalid_dir = skill_root / "invalid"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "SKILL.md").write_text("# Missing frontmatter", encoding="utf-8")
    write_skill(skill_root, "python-repository", metadata_name="different-name")

    with pytest.raises(SkillFormatError, match="must start"):
        SkillParser().parse_metadata(invalid_dir / "SKILL.md", skill_root)
    with pytest.raises(SkillFormatError, match="must match directory"):
        SkillParser().parse_metadata(
            skill_root / "python-repository" / "SKILL.md",
            skill_root,
        )


def test_activate_skill_loads_body_for_next_llm_call_and_persists_record(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skills"
    body = "# Instructions\nRun pytest tests/test_target.py."
    write_skill(skill_root, "python-repository", content=body)
    registry = SkillRegistry(skill_root)
    session = SkillSession(registry)
    config = AgentConfig(max_steps=3)
    context = ToolContext(
        run_id="run-1",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path / "workspace",
        run_dir=tmp_path / "runs" / "run-1",
        config=config,
    )
    llm = ActivateThenFinishLLM()
    tool = ActivateSkillTool(session, SkillActivationStore(context.run_dir))
    loop = AgentLoop(
        config=config,
        llm=llm,  # type: ignore[arg-type]
        tools=ToolRegistry([tool]),
        context=context,
        hooks=[SkillActivationHook(session)],
    )
    initial = PromptAssembler().assemble(
        PromptRequest(
            user_request="Fix tests.",
            repo_url=context.repo_url,
            context=RunContextSnapshot(repo_url=context.repo_url, max_steps=3),
            available_skills=registry.list_metadata(),
        )
    ).messages

    result = loop.run(RunSummary(run_id="run-1", repo_url=context.repo_url), initial)

    assert result.status == "succeeded"
    assert any(body in message.content for message in llm.second_call_messages)
    tool_message = next(message for message in result.messages if message.role == "tool")
    assert body not in tool_message.content
    records = [
        json.loads(line)
        for line in (context.run_dir / "skill_activations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records[0]["skill_name"] == "python-repository"
    assert records[0]["newly_activated"]


def test_activate_skill_does_not_inject_body_twice(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    write_skill(skill_root, "python-repository")
    session = SkillSession(SkillRegistry(skill_root))
    tool = ActivateSkillTool(session)
    context = ToolContext(
        run_id="run-1",
        repo_url="https://example.com/repo.git",
        workspace_path=tmp_path,
        run_dir=tmp_path / "run-1",
        config=AgentConfig(),
    )
    hook = SkillActivationHook(session)
    tool_use = ToolUseRequest(
        id="skill-1",
        name="activate_skill",
        input={"name": "python-repository"},
    )

    first = tool.invoke(tool_use.input, context)
    first_hook = hook.after_tool_call(context, tool, tool_use, first, 0.0)
    second = tool.invoke(tool_use.input, context)
    second_hook = hook.after_tool_call(context, tool, tool_use, second, 0.0)

    assert first.data["newly_activated"]
    assert first_hook is not None
    assert not second.data["newly_activated"]
    assert second_hook is None


def test_context_builder_extracts_bounded_tool_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".git").mkdir(parents=True)
    messages = [
        AgentMessage(
            role="assistant",
            content="read",
            tool_uses=[
                ToolUseRequest(id="read-1", name="read_file", input={"path": "README.md"})
            ],
        ),
        AgentMessage(
            role="tool",
            tool_call_id="read-1",
            content=json.dumps({"success": True, "summary": "read README"}),
        ),
    ]

    snapshot = RunContextBuilder().build(
        repo_url="https://example.com/repo.git",
        workspace_path=workspace,
        current_step=2,
        max_steps=20,
        messages=messages,
    )

    assert snapshot.workspace_state == "ready"
    assert snapshot.inspected_files == ["README.md"]
    assert snapshot.failures == []
