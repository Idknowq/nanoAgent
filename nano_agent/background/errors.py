from nano_agent.tools.errors import ToolError


class BackgroundJobError(ToolError):
    """Expected background job failure with a stable tool-facing code."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code  # 暴露给后台任务工具的稳定错误码。
