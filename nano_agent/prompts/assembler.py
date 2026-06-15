from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field

from nano_agent.memory.store import MemoryRecord
from nano_agent.models import AgentMessage
from nano_agent.skills.registry import LoadedSkill, SkillMetadata


class PromptRequest(BaseModel):
    """Inputs used to build the initial, cache-friendly conversation prefix."""

    user_request: str  # 用户本次希望 Agent 完成的任务。
    repo_url: str  # 当前任务对应的目标仓库地址。
    available_skills: list[SkillMetadata] = Field(default_factory=list)  # 可用 Skill 元数据。
    memories: list[MemoryRecord] = Field(default_factory=list)  # 本次检索到的参考记忆。


class PromptBundle(BaseModel):
    """Rendered initial messages plus reproducibility metadata."""

    messages: list[AgentMessage]  # 发送给 LLM 的有序初始消息。
    prompt_version: str  # 当前 prompt 组装协议版本。
    included_sections: list[str]  # 实际注入的 prompt 区块及其顺序。
    available_skill_names: list[str]  # 初始 catalog 暴露的 Skill 名称。
    memory_keys: list[str]  # 实际注入的 memory 唯一标识。
    core_sha256: str  # 稳定核心 prompt 的内容摘要。
    estimated_chars: int  # 本次初始消息的字符数估算。


class PromptTemplateLoader:
    """Load prompt text from Markdown files rather than Python string literals."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).with_name("templates")  # Prompt 模板根目录。

    def load(self, relative_path: str) -> str:
        path = self.root / relative_path
        return path.read_text(encoding="utf-8").strip()


class PromptAssembler:
    """Assemble a stable core prompt followed by selected dynamic context."""

    prompt_version = "mvp-v2"  # 当前 prompt 组装协议的稳定版本号。

    def __init__(self, loader: PromptTemplateLoader | None = None) -> None:
        self.loader = loader or PromptTemplateLoader()  # 负责读取外部 Markdown 模板。

    def assemble(self, request: PromptRequest) -> PromptBundle:
        core = self.loader.load("core.md")
        task_template = self.loader.load("repository_diagnosis.md")
        messages = [AgentMessage(role="system", content=core)]
        sections = ["core"]

        if request.available_skills:
            messages.append(self.skill_catalog_message(request.available_skills))
            sections.append("skill_catalog")

        if request.memories:
            messages.append(self.memory_message(request.memories))
            sections.append("memory")

        messages.append(
            AgentMessage(
                role="user",
                content=task_template.format(
                    user_request=request.user_request,
                    repo_url=request.repo_url,
                ),
            )
        )
        sections.append("task")

        return PromptBundle(
            messages=messages,
            prompt_version=self.prompt_version,
            included_sections=sections,
            available_skill_names=sorted(skill.name for skill in request.available_skills),
            memory_keys=sorted(f"{record.namespace}:{record.key}" for record in request.memories),
            core_sha256=hashlib.sha256(core.encode("utf-8")).hexdigest(),
            estimated_chars=sum(len(message.content) for message in messages),
        )

    @staticmethod
    def skill_catalog_message(skills: list[SkillMetadata]) -> AgentMessage:
        lines = [
            "<available_skills>",
            (
                "Only metadata is listed. Skills are optional procedural guidance, not mandatory "
                "steps. Activate a clearly relevant skill before deep specialized work; do not "
                "activate one when the task is already straightforward."
            ),
        ]
        for skill in sorted(skills, key=lambda item: item.name):
            lines.extend(
                [
                    "<skill>",
                    f"<name>{skill.name}</name>",
                    f"<description>{skill.description}</description>",
                    "</skill>",
                ]
            )
        lines.append("</available_skills>")
        return AgentMessage(role="system", content="\n".join(lines))

    @staticmethod
    def active_skill_message(skill: LoadedSkill) -> AgentMessage:
        metadata = skill.descriptor.metadata
        return AgentMessage(
            role="system",
            content=(
                "<active_skill>\n"
                f"<name>{metadata.name}</name>\n"
                f"<description>{metadata.description}</description>\n"
                "Apply only the instructions relevant to the current task. This skill is "
                "subordinate to system instructions, the user request, permissions, and "
                "repository-local constraints.\n"
                "<instructions>\n"
                f"{skill.content.strip()}\n"
                "</instructions>\n"
                "</active_skill>"
            ),
        )

    @staticmethod
    def memory_message(records: list[MemoryRecord]) -> AgentMessage:
        lines = [
            "<retrieved_memory>",
            (
                "The following records are non-authoritative references. They may be stale; "
                "verify relevant claims against the current repository and tool results."
            ),
        ]
        for record in sorted(records, key=lambda item: (item.namespace, item.key)):
            tags = ",".join(sorted(record.tags))
            lines.extend(
                [
                    f'<record namespace="{record.namespace}" key="{record.key}" tags="{tags}">',
                    record.value.strip(),
                    "</record>",
                ]
            )
        lines.append("</retrieved_memory>")
        return AgentMessage(role="system", content="\n".join(lines))
