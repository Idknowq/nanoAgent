from __future__ import annotations

import random
from collections.abc import Callable

from nano_agent.services.errors import LLMServiceError


class RetryPolicy:
    """Compute bounded exponential-backoff delays for transient LLM errors."""

    def __init__(
        self,
        *,
        base_seconds: float,
        max_seconds: float,
        jitter_seconds: float,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.base_seconds = base_seconds
        self.max_seconds = max_seconds
        self.jitter_seconds = jitter_seconds
        self.random_uniform = random_uniform

    def delay_seconds(self, error: LLMServiceError, retry_index: int) -> float:
        if error.retry_after_seconds is not None:
            return error.retry_after_seconds
        exponential = min(self.max_seconds, self.base_seconds * (2 ** (retry_index - 1)))
        jitter = self.random_uniform(0.0, self.jitter_seconds)
        return exponential + jitter
