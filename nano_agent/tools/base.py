from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from nano_agent.models import ApprovalLevel


class ToolResult(BaseModel):
    """通用工具执行结果的最小形态。"""

    success: bool  # 工具是否成功完成。
    summary: str  # 工具输出的简短摘要，供 Agent 决策和 run summary 使用。
    data: dict[str, Any] = Field(default_factory=dict)  # 工具返回的结构化数据。


class ToolSpec(BaseModel):
    """工具元数据，用于后续暴露给 planner、LLM 或 MCP。"""

    name: str  # 工具唯一名称。
    description: str  # 工具用途说明。
    approval_level: ApprovalLevel  # 工具调用所需的默认权限等级。
    input_schema: dict = Field(default_factory=dict)  # 工具输入结构。


class RuntimeTool(ABC):
    """Agent loop 可直接调用的运行时工具接口。"""

    name: ClassVar[str]  # 工具唯一名称。
    description: ClassVar[str]  # 工具用途说明。
    approval_level: ClassVar[ApprovalLevel] = ApprovalLevel.READ  # 工具默认权限等级。
    input_schema: ClassVar[dict[str, Any]] = {}  # 暴露给 LLM 的 JSON Schema 参数结构。

    @abstractmethod
    def run(self, input_data: dict[str, Any]) -> ToolResult:
        """执行工具并返回统一结果。"""


class ToolRegistry:
    """运行时工具注册表，供 Agent loop 按名称查找工具。"""

    def __init__(self, tools: list[RuntimeTool] | None = None) -> None:
        self._tools: dict[str, RuntimeTool] = {}  # 保存工具名称到工具实例的映射。
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: RuntimeTool) -> None:
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
            )
            for tool in self._tools.values()
        ]
