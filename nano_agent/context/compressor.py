from __future__ import annotations


class ContextCompressor:
    """上下文压缩器占位实现。

    当前只做头尾截断。后续可以替换为基于 LLM 或规则的摘要器，并保留文件路径、
    错误信息、已执行动作和当前假设等关键事实。
    """

    def compress(self, text: str, max_chars: int = 8_000) -> str:
        if len(text) <= max_chars:
            return text
        head = text[: max_chars // 2]
        tail = text[-max_chars // 2 :]
        return f"{head}\n\n[...context compressed...]\n\n{tail}"
