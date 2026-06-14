from nano_agent.tools.errors import ToolError


class TaskError(ToolError):
    """Expected task operation failure with a stable tool-facing code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code  # 暴露给 Task 工具的稳定错误码。
