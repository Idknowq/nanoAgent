from __future__ import annotations

from datetime import datetime, timezone

from nano_agent.config import AgentConfig
from nano_agent.hooks.registry import build_default_hooks
from nano_agent.loop import AgentLoop
from nano_agent.models import RunStatus, RunSummary
from nano_agent.persistence.config_store import ConfigStore
from nano_agent.persistence.message_store import MessageStore
from nano_agent.prompts.assembler import PromptAssembler
from nano_agent.services.llm import LLMClient
from nano_agent.services.registry import create_llm_client
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

    def run(self, repo_url: str) -> RunSummary:
        run = self.workspace_manager.create_run(repo_url=repo_url)
        run.status = RunStatus.RUNNING

        try:
            workspace_path = self.workspace_manager.next_workspace_path(repo_url, run.run_id)
            run_dir = self.workspace_manager.run_dir(run.run_id)
            run.workspace_path = workspace_path
            run.artifacts = {
                "config": "config.json",
                "llm_calls": "llm_calls.jsonl",
                "audit": "audit.jsonl",
                "summary": "summary.json",
                "messages": "messages.jsonl",
            }
            self.config_store.save(run.run_id, run_dir, self.config)
            self.workspace_manager.save_run_summary(run)
            context = ToolContext(
                run_id=run.run_id,
                repo_url=repo_url,
                workspace_path=workspace_path,
                run_dir=run_dir,
                config=self.config,
                max_steps=self.config.max_steps,
            )
            llm = self.llm or create_llm_client(self.config, repo_url)
            tools = build_default_tool_registry(context)
            hooks = build_default_hooks(self.config)
            initial_messages = self.prompt_assembler.build_initial_messages(repo_url, tools.specs())
            loop = AgentLoop(
                config=self.config,
                llm=llm,
                tools=tools,
                context=context,
                hooks=hooks,
                message_store=MessageStore(run_dir),
            )
            run = loop.run(run=run, initial_messages=initial_messages)
        except Exception as exc:  # noqa: BLE001 - top-level agent boundary should capture failures.
            run.status = RunStatus.FAILED
            run.notes.append(f"Agent failed: {exc}")

        run.finished_at = datetime.now(timezone.utc)
        self.workspace_manager.save_run_summary(run)
        return run
