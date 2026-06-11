class ToolError(Exception):
    """Expected tool failure that can be returned to the LLM."""

    code = "tool_error"


class ToolInputError(ToolError):
    code = "invalid_input"


class ToolExecutionError(ToolError):
    code = "execution_error"


class ToolTimeoutError(ToolError):
    code = "timeout"
