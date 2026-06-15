from __future__ import annotations

from threading import Event


class AgentCancelledError(RuntimeError):
    """Raised when cooperative cancellation reaches a safe execution boundary."""


class CancellationToken:
    """Thread-safe cooperative cancellation signal shared with one running job."""

    def __init__(self) -> None:
        self._event = Event()  # 保存当前 Job 是否收到取消请求。

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise AgentCancelledError("Background job cancellation was requested.")

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)
