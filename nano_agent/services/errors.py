from __future__ import annotations

from enum import StrEnum
from typing import Any


class LLMErrorKind(StrEnum):
    """Provider-independent classification for LLM request failures."""

    RATE_LIMIT = "rate_limit"
    OVERLOADED = "overloaded"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    PROMPT_TOO_LONG = "prompt_too_long"
    OUTPUT_TRUNCATED = "output_truncated"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


TRANSIENT_LLM_ERROR_KINDS = frozenset(
    {
        LLMErrorKind.RATE_LIMIT,
        LLMErrorKind.OVERLOADED,
        LLMErrorKind.TIMEOUT,
        LLMErrorKind.CONNECTION,
    }
)


class LLMServiceError(RuntimeError):
    """Structured failure raised by an LLM provider adapter."""

    def __init__(
        self,
        message: str,
        *,
        kind: LLMErrorKind,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
        invalid_tool_name: str | None = None,
        invalid_tool_arguments_preview: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.invalid_tool_name = invalid_tool_name
        self.invalid_tool_arguments_preview = invalid_tool_arguments_preview

    @property
    def retryable(self) -> bool:
        return self.kind in TRANSIENT_LLM_ERROR_KINDS


def normalize_llm_error(error: Exception) -> LLMServiceError:
    """Convert SDK and provider failures into a stable error shape."""

    if isinstance(error, LLMServiceError):
        return error

    status_code = _status_code(error)
    message = str(error)
    kind = _classify(error, status_code, message)
    return LLMServiceError(
        message or type(error).__name__,
        kind=kind,
        status_code=status_code,
        retry_after_seconds=_retry_after_seconds(error),
    )


def _classify(error: Exception, status_code: int | None, message: str) -> LLMErrorKind:
    if _is_prompt_too_long(error, message):
        return LLMErrorKind.PROMPT_TOO_LONG

    class_name = type(error).__name__.lower()
    if status_code == 429 or "ratelimit" in class_name or "rate_limit" in class_name:
        return LLMErrorKind.RATE_LIMIT
    if status_code in {502, 503, 504, 529}:
        return LLMErrorKind.OVERLOADED
    if "timeout" in class_name:
        return LLMErrorKind.TIMEOUT
    if "connection" in class_name:
        return LLMErrorKind.CONNECTION
    if status_code in {401, 403} or "authentication" in class_name or "permission" in class_name:
        return LLMErrorKind.AUTHENTICATION
    if status_code == 400 or "badrequest" in class_name:
        return LLMErrorKind.INVALID_REQUEST
    return LLMErrorKind.UNKNOWN


def _is_prompt_too_long(error: Exception, message: str) -> bool:
    code = getattr(error, "code", None)
    if code is None:
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            nested = body.get("error")
            nested_code = nested.get("code") if isinstance(nested, dict) else None
            code = body.get("code") or nested_code
    if str(code).lower() in {
        "context_length_exceeded",
        "max_context_window",
        "prompt_is_too_long",
        "prompt_too_long",
    }:
        return True
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "context_length_exceeded",
            "maximum context length",
            "max_context_window",
            "prompt is too long",
            "prompt_too_long",
            "too many tokens",
        )
    )


def _status_code(error: Exception) -> int | None:
    value = getattr(error, "status_code", None)
    if isinstance(value, int):
        return value
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _retry_after_seconds(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers: Any = getattr(response, "headers", None)
    if headers is None:
        headers = getattr(error, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)
