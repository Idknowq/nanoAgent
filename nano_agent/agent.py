from __future__ import annotations

from nano_agent.config import AgentConfig
from nano_agent.loop import AgentLoop
from nano_agent.models import AgentMessage, RunStatus, RunSummary
from nano_agent.services.llm import LLMClient, ScriptedMvpLLMClient
from nano_agent.services.openai_compatible import OpenAICompatibleLLMClient
from nano_agent.tools.base import ToolRegistry
from nano_agent.tools.bash import BashTool
from nano_agent.tools.todo import TodoWriteTool
from nano_agent.workspace import WorkspaceManager


class NanoAgent:
    """单 Agent 运行入口，负责准备上下文并启动 LLM 工具调用循环。

    核心执行模型不是固定 pipeline，而是 LLM 返回 tool_use 时调用工具，拿到
    tool_result 后继续喂回 LLM，直到 LLM 返回 end_turn。
    """

    def __init__(self, config: AgentConfig, llm: LLMClient | None = None) -> None:
        self.config = config  # 保存本次 Agent 运行的全局配置。
        self.workspace_manager = WorkspaceManager(config=config)  # 管理工作区、clone 和运行记录。
        self.llm = llm  # 保存可替换的 LLM 客户端；为空时使用 MVP 脚本客户端。

    def run(self, repo_url: str) -> RunSummary:
        run = self.workspace_manager.create_run(repo_url=repo_url)
        run.status = RunStatus.RUNNING

        try:
            workspace_path = self.workspace_manager.next_workspace_path(repo_url, run.run_id)
            run.workspace_path = workspace_path
            llm = self.llm or self._create_default_llm(repo_url)
            tools = ToolRegistry(
                tools=[
                    BashTool(config=self.config, cwd=workspace_path),
                    TodoWriteTool(),
                ]
            )
            loop = AgentLoop(config=self.config, llm=llm, tools=tools)
            run = loop.run(run=run, initial_messages=self._initial_messages(repo_url))
        except Exception as exc:  # noqa: BLE001 - top-level agent boundary should capture failures.
            run.status = RunStatus.FAILED
            run.notes.append(f"Agent failed: {exc}")

        self.workspace_manager.save_run_summary(run)
        return run

    def _create_default_llm(self, repo_url: str) -> LLMClient:
        if self.config.llm_provider == "scripted":
            return ScriptedMvpLLMClient(repo_url=repo_url)
        if self.config.llm_provider == "deepseek":
            return OpenAICompatibleLLMClient.from_deepseek_env(model=self.config.llm_model)
        raise ValueError(f"Unsupported llm provider: {self.config.llm_provider}")

    def _initial_messages(self, repo_url: str) -> list[AgentMessage]:
        return [
            AgentMessage(
                role="system",
                content=(
                    "You are nanoAgent. Work in a loop: decide whether to call tools, "
                    "read tool results, then continue until you can end_turn. "
                    "Use bash as the primary execution tool. Use todo_write only when "
                    "a short-lived session task list is useful."
                ),
            ),
            AgentMessage(
                role="user",
                content=f"Analyze this GitHub repository and prepare for diagnosis: {repo_url}",
            ),
        ]
