from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from nano_agent.config import AgentConfig
from nano_agent.context.compactor import CompactionStore, ContextCompactor
from nano_agent.context.snapshot import RunContextSnapshot
from nano_agent.hooks.registry import build_default_hooks
from nano_agent.hooks.skill_activation import SkillActivationHook
from nano_agent.loop import AgentLoop
from nano_agent.memory.store import JsonlMemoryStore, MemoryRecord
from nano_agent.models import RunStatus, RunSummary
from nano_agent.persistence.config_store import ConfigStore
from nano_agent.persistence.message_store import MessageStore
from nano_agent.persistence.prompt_store import PromptStore
from nano_agent.persistence.skill_activation_store import SkillActivationStore
from nano_agent.prompts.assembler import PromptAssembler, PromptRequest
from nano_agent.services.llm import LLMClient
from nano_agent.services.registry import create_llm_client
from nano_agent.skills.registry import SkillRegistry
from nano_agent.skills.session import SkillSession
from nano_agent.tools.activate_skill import ActivateSkillTool
from nano_agent.tools.base import ToolContext, build_default_tool_registry
from nano_agent.workspace import WorkspaceManager


class NanoAgent:
    """单 Agent 运行入口，负责准备上下文并启动 LLM 工具调用循环。

    核心执行模型不是固定 pipeline，而是 LLM 返回 tool_use 时调用工具，拿到
    tool_result 后继续喂回 LLM，直到 LLM 返回 end_turn。
    """

    def __init__(self, config: AgentConfig, llm: LLMClient | None = None) -> None:
        self.config = config  # 保存本次 Agent 运行的全局配置。
        self.workspace_manager = WorkspaceManager(config=config)  # 管理工作区、clone 和运行记录。
        self.llm = llm  # 保存可替换的 LLM 客户端；为空时按配置创建真实模型客户端。
        self.prompt_assembler = PromptAssembler()  # 组装初始 system/user 消息。
        self.config_store = ConfigStore()
        self.prompt_store = PromptStore()  # 持久化本次 prompt 的组装元数据。

    def run(self, repo_url: str) -> RunSummary:
        run = self.workspace_manager.create_run(repo_url=repo_url)
        run.status = RunStatus.RUNNING

        try:
            workspace_path = self.workspace_manager.next_workspace_path(repo_url, run.run_id)
            run_dir = self.workspace_manager.run_dir(run.run_id)
            run.workspace_path = workspace_path
            run.artifacts = {
                "config": "config.json",
                "summary": "summary.json",
                "messages": "messages.jsonl",
                "prompt": "prompt.json",
                "context_checkpoint": "context_checkpoint.json",
            }
            if self.config.llm_calls_enabled:
                run.artifacts["llm_calls"] = "llm_calls.jsonl"
            if self.config.audit_enabled:
                run.artifacts["audit"] = "audit.jsonl"
            self.config_store.save(run.run_id, run_dir, self.config)
            self.workspace_manager.save_run_summary(run)
            context = ToolContext(
                run_id=run.run_id,
                repo_url=repo_url,
                workspace_path=workspace_path,
                run_dir=run_dir,
                runtime_dir=run_dir / "runtime",
                config=self.config,
                max_steps=self.config.max_steps,
            )
            llm = self.llm or create_llm_client(self.config, repo_url)
            tools = build_default_tool_registry(context)
            skill_registry = SkillRegistry(self._skills_root())
            skill_session = SkillSession(skill_registry)
            tools.register(
                ActivateSkillTool(
                    skill_session,
                    activation_store=SkillActivationStore(run_dir),
                )
            )
            hooks = [
                SkillActivationHook(skill_session),
                *build_default_hooks(self.config),
            ]
            prompt_bundle = self.prompt_assembler.assemble(
                PromptRequest(
                    user_request=(
                        "Analyze the repository, diagnose defects, and make verified repairs."
                    ),
                    repo_url=repo_url,
                    context=RunContextSnapshot(
                        repo_url=repo_url,
                        max_steps=self.config.max_steps,
                    ),
                    available_skills=skill_registry.list_metadata(),
                    memories=self._load_memories(repo_url),
                )
            )
            self.prompt_store.save(run.run_id, run_dir, prompt_bundle)
            message_store = MessageStore(run_dir)
            compactor = ContextCompactor(
                config=self.config,
                llm=llm,
                store=CompactionStore(run.run_id, run_dir, message_store),
                repo_url=repo_url,
                workspace_path=workspace_path,
            )
            loop = AgentLoop(
                config=self.config,
                llm=llm,
                tools=tools,
                context=context,
                hooks=hooks,
                message_store=message_store,
                compactor=compactor,
            )
            run = loop.run(run=run, initial_messages=prompt_bundle.messages)
        except Exception as exc:  # noqa: BLE001 - top-level agent boundary should capture failures.
            run.status = RunStatus.FAILED
            run.notes.append(f"Agent failed: {exc}")

        run.finished_at = datetime.now(timezone.utc)
        self.workspace_manager.save_run_summary(run)
        return run

    def _skills_root(self) -> Path:
        return self.config.skills_root or Path(__file__).with_name("skills") / "builtin"

    def _load_memories(self, repo_url: str) -> list[MemoryRecord]:
        if self.config.memory_path is None or self.config.memory_limit == 0:
            return []
        store = JsonlMemoryStore(self.config.memory_path)
        repo_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
        tagged = store.search(
            ["repo", "failure", "run"],
            tags={repo_url, repo_name},
            limit=self.config.memory_limit,
        )
        remaining = self.config.memory_limit - len(tagged)
        if remaining <= 0:
            return tagged
        preferences = store.search("user_preference", limit=remaining)
        seen = {(record.namespace, record.key) for record in tagged}
        return tagged + [
            record
            for record in preferences
            if (record.namespace, record.key) not in seen
        ][:remaining]
