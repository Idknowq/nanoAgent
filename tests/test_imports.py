from nano_agent.agent import NanoAgent
from nano_agent.config import AgentConfig
from nano_agent.context.compressor import ContextCompressor
from nano_agent.memory.store import JsonlMemoryStore
from nano_agent.hooks.permission import PermissionPolicy
from nano_agent.prompts.assembler import PromptAssembler
from nano_agent.skills.registry import SkillRegistry
from nano_agent.workspace import WorkspaceManager


def test_core_components_can_be_constructed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = AgentConfig(workspace_root=tmp_path / "workspaces", runs_root=tmp_path / "runs")

    agent = NanoAgent(config=config)
    workspace_manager = WorkspaceManager(config=config)

    assert agent
    assert workspace_manager.next_workspace_path("https://github.com/example/repo.git", "run-1").name
    assert ContextCompressor().compress("abc") == "abc"
    assert PermissionPolicy().requires_approval(level="write")
    assert SkillRegistry(root=config.workspace_root).list_metadata() == []
    assert JsonlMemoryStore(tmp_path / "memory.jsonl").search("repo") == []
    assert PromptAssembler()
