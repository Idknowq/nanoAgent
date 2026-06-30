from __future__ import annotations

import asyncio


class AgentCancelledError(RuntimeError):
    """Raised when cooperative cancellation reaches a safe execution boundary."""


class CancellationToken:
    """Async cooperative cancellation signal shared with one running job."""

    def __init__(self) -> None:
        self._event = asyncio.Event()  # 保存当前 Job 是否收到取消请求。

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise AgentCancelledError("Background job cancellation was requested.")

    async def wait(self, timeout: float) -> bool:
        """Wait until cancellation is requested or the timeout expires."""

        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True
