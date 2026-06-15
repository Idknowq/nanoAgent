from __future__ import annotations

import json

from nano_agent.background.presentation import public_job_data
from nano_agent.background.supervisor import BackgroundJobSupervisor
from nano_agent.hooks.base import HookResult, NoOpHook
from nano_agent.models import AgentMessage


class BackgroundCompletionHook(NoOpHook):
    """Inject each completed background job into the parent conversation exactly once."""

    def __init__(self, supervisor: BackgroundJobSupervisor) -> None:
        self.supervisor = supervisor  # 提供当前主运行尚未消费的后台完成事件。

    def before_llm_call(self, context, messages, tools) -> HookResult | None:  # type: ignore[no-untyped-def]
        del context, messages, tools
        events = self.supervisor.drain_events()
        if not events:
            return None
        payload = [
            public_job_data(
                self.supervisor.get(event.job_id),
                self.supervisor.max_result_chars,
            )
            for event in events
        ]
        return HookResult(
            injected_messages=[
                AgentMessage(
                    role="system",
                    content=(
                        "<background_job_updates>\n"
                        "These Jobs reached terminal states. Consume their included results; "
                        "do not poll them again unless required data is missing.\n"
                        f"{json.dumps(payload, ensure_ascii=False)}\n"
                        "</background_job_updates>"
                    ),
                )
            ]
        )
