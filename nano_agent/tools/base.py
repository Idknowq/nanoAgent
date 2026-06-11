from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nano_agent.config import AgentConfig
from nano_agent.models import ApprovalLevel
from nano_agent.tools.errors import ToolError


class ToolResult(BaseModel):
    """通用工具执行结果的最小形态。"""

    success: bool  # 工具是否成功完成。
    summary: str  # 工具输出的简短摘要，供 Agent 决策和 run summary 使用。
    data: dict[str, Any] = Field(default_factory=dict)  # 工具返回的结构化数据。
    error_code: str | None = None  # 稳定错误类型，供 LLM 和审计逻辑判断。
    error_message: str | None = None  # 面向调用方的错误说明。

    @classmethod
    def failure(
        cls,
        *,
        code: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> ToolResult:
        return cls(
            success=False,
            summary=message,
            data=data or {},
            error_code=code,
            error_message=message,
        )


class ToolSpec(BaseModel):
    """工具元数据，用于后续暴露给 planner、LLM 或 MCP。"""

    name: str  # 工具唯一名称。
    description: str  # 工具用途说明。
    approval_level: ApprovalLevel  # 工具调用所需的默认权限等级。
    input_schema: dict = Field(default_factory=dict)  # 工具输入结构。
    category: str = "general"  # 工具分类，用于 prompt 分组和权限策略。
    enabled: bool = True  # 工具是否默认可用。
    requires_workspace: bool = False  # 工具是否依赖当前 run 的工作区。
    is_mutating: bool = False  # 工具是否可能修改文件、环境或外部状态。


class ToolContext(BaseModel):
    """一次工具调用可访问的运行上下文。"""

    run_id: str  # 当前 Agent run 的唯一标识。
    repo_url: str  # 用户输入的目标仓库地址。
    workspace_path: Path  # 当前 run 的隔离工作区路径。
    run_dir: Path  # 当前 run 的持久化目录，由各组件写入自己的文件。
    config: AgentConfig  # 当前 Agent 的全局配置。
    current_step: int = 0  # 当前 Agent loop 步骤，供 hook 展示和限流使用。
    max_steps: int = 0  # 当前 Agent loop 最大步骤数。


class ToolInput(BaseModel):
    """Base model for validated tool input."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RuntimeTool(ABC):
    """Agent loop 可直接调用的运行时工具接口。"""

    name: ClassVar[str]  # 工具唯一名称。
    description: ClassVar[str]  # 工具用途说明。
    approval_level: ClassVar[ApprovalLevel] = ApprovalLevel.READ  # 工具默认权限等级。
    input_schema: ClassVar[dict[str, Any]] = {}  # 暴露给 LLM 的 JSON Schema 参数结构。
    category: ClassVar[str] = "general"  # 工具分类。
    enabled: ClassVar[bool] = True  # 工具是否默认可用。
    requires_workspace: ClassVar[bool] = False  # 工具是否依赖当前工作区。
    workspace_must_exist: ClassVar[bool] = True  # 调用前工作区是否必须已存在。
    is_mutating: ClassVar[bool] = False  # 工具是否可能修改环境或外部状态。
    input_model: ClassVar[type[BaseModel] | None] = None  # 工具运行时输入校验模型。

    def invoke(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        """Validate common preconditions and convert expected failures to results."""
        if self.requires_workspace:
            workspace = context.workspace_path
            if workspace.exists() and not workspace.is_dir():
                return ToolResult.failure(
                    code="workspace_unavailable",
                    message="agent workspace is not a directory",
                )
            if self.workspace_must_exist and not workspace.is_dir():
                return ToolResult.failure(
                    code="workspace_unavailable",
                    message="agent workspace is unavailable",
                )

        try:
            validated = self.validate_input(input_data)
            return self.run(validated, context)
        except ValidationError as exc:
            return ToolResult.failure(code="invalid_input", message=str(exc))
        except ToolError as exc:
            return ToolResult.failure(code=exc.code, message=str(exc))

    def validate_input(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if self.input_model is None:
            return input_data
        validated = self.input_model.model_validate(input_data)
        return validated.model_dump()

    @abstractmethod
    def run(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        """执行工具并返回统一结果。"""


ToolFactory = Callable[[ToolContext], RuntimeTool]
_TOOL_FACTORIES: dict[str, ToolFactory] = {}


class ToolRegistry:
    """运行时工具注册表，供 Agent loop 按名称查找工具。"""

    def __init__(self, tools: list[RuntimeTool] | None = None) -> None:
        self._tools: dict[str, RuntimeTool] = {}  # 保存工具名称到工具实例的映射。
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: RuntimeTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> RuntimeTool:
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        return self._tools[name]

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=tool.name,
                description=tool.description,
                approval_level=tool.approval_level,
                input_schema=tool.input_schema,
                category=tool.category,
                enabled=tool.enabled,
                requires_workspace=tool.requires_workspace,
                is_mutating=tool.is_mutating,
            )
            for tool in self._tools.values()
            if tool.enabled
        ]


def register_tool_factory(name: str, factory: ToolFactory) -> None:
    """注册工具工厂，供工具模块自注册使用。"""
    if name in _TOOL_FACTORIES and _TOOL_FACTORIES[name] is not factory:
        raise ValueError(f"Tool factory already registered: {name}")
    _TOOL_FACTORIES[name] = factory


def build_default_tool_registry(context: ToolContext) -> ToolRegistry:
    """基于已注册工具工厂构建默认工具注册表。"""
    _import_builtin_tools()
    return ToolRegistry([factory(context) for factory in _TOOL_FACTORIES.values()])


def _import_builtin_tools() -> None:
    """导入内置工具模块，触发模块级工具工厂注册。"""
    import nano_agent.tools.clone_repo  # noqa: F401
    import nano_agent.tools.list_files  # noqa: F401
    import nano_agent.tools.read_file  # noqa: F401
    import nano_agent.tools.run_command  # noqa: F401
    import nano_agent.tools.todo  # noqa: F401
