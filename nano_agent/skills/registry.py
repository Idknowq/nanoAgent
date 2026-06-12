from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillFormatError(ValueError):
    """Raised when a SKILL.md file does not satisfy the supported format."""


class SkillMetadata(BaseModel):
    """YAML frontmatter fields exposed to the model before skill activation."""

    name: str  # Skill 的稳定名称，必须与目录名一致。
    description: str = Field(min_length=1, max_length=1024)  # Skill 用途和触发条件。
    compatibility: str | None = None  # 可选的运行环境兼容性说明。
    metadata: dict[str, str] = Field(default_factory=dict)  # 可选的扩展元数据。
    allowed_tools: list[str] = Field(default_factory=list, alias="allowed-tools")  # 工具提示。

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not SKILL_NAME_PATTERN.fullmatch(value):
            raise ValueError("name must use lowercase letters, digits, and single hyphens")
        return value


class SkillDescriptor(BaseModel):
    """A discovered skill whose body has not been loaded."""

    metadata: SkillMetadata  # 已解析并可注入 catalog 的 frontmatter。
    root: Path  # Skill 目录的规范化绝对路径。
    entrypoint: Path  # Skill 主文件 SKILL.md 的规范化绝对路径。
    content_offset: int  # Markdown 正文在 SKILL.md 中的字节偏移。


class LoadedSkill(BaseModel):
    """A skill body loaded only after an explicit activation request."""

    descriptor: SkillDescriptor  # 正文对应的已注册 Skill 描述。
    content: str  # 不包含 YAML frontmatter 的 Markdown 正文。
    content_sha256: str  # Skill 正文内容摘要，用于审计和缓存识别。


class SkillParser:
    """Parse bounded YAML frontmatter first and load the body on demand."""

    def __init__(
        self,
        *,
        max_frontmatter_bytes: int = 16_384,
        max_content_bytes: int = 256_000,
    ) -> None:
        self.max_frontmatter_bytes = max_frontmatter_bytes  # Frontmatter 最大字节数。
        self.max_content_bytes = max_content_bytes  # Skill 正文最大字节数。

    def parse_metadata(self, path: Path, skills_root: Path) -> SkillDescriptor:
        root = self._resolve_within(skills_root, path.parent)
        entrypoint = self._resolve_within(root, path)
        if entrypoint.name != "SKILL.md" or not entrypoint.is_file():
            raise SkillFormatError(f"skill entrypoint must be a regular SKILL.md: {path}")

        frontmatter, content_offset = self._read_frontmatter(entrypoint)
        try:
            raw = yaml.safe_load(frontmatter)
        except yaml.YAMLError as exc:
            raise SkillFormatError(f"invalid YAML frontmatter in {entrypoint}: {exc}") from exc
        if not isinstance(raw, dict):
            raise SkillFormatError(f"frontmatter must be a YAML mapping: {entrypoint}")
        try:
            metadata = SkillMetadata.model_validate(raw)
        except ValidationError as exc:
            raise SkillFormatError(f"invalid skill metadata in {entrypoint}: {exc}") from exc
        if metadata.name != root.name:
            raise SkillFormatError(
                f"skill name '{metadata.name}' must match directory name '{root.name}'"
            )
        return SkillDescriptor(
            metadata=metadata,
            root=root,
            entrypoint=entrypoint,
            content_offset=content_offset,
        )

    def load_content(self, descriptor: SkillDescriptor) -> LoadedSkill:
        entrypoint = self._resolve_within(descriptor.root, descriptor.entrypoint)
        try:
            with entrypoint.open("rb") as file:
                file.seek(descriptor.content_offset)
                data = file.read(self.max_content_bytes + 1)
        except OSError as exc:
            raise SkillFormatError(f"failed to read skill body: {exc}") from exc
        if len(data) > self.max_content_bytes:
            raise SkillFormatError(
                f"skill body exceeds max_content_bytes={self.max_content_bytes}"
            )
        content = data.decode("utf-8", errors="strict").strip()
        if not content:
            raise SkillFormatError(f"skill body is empty: {entrypoint}")
        return LoadedSkill(
            descriptor=descriptor,
            content=content,
            content_sha256=hashlib.sha256(data).hexdigest(),
        )

    def _read_frontmatter(self, path: Path) -> tuple[str, int]:
        try:
            with path.open("rb") as file:
                first = file.readline()
                if first.rstrip(b"\r\n") != b"---":
                    raise SkillFormatError(f"SKILL.md must start with YAML frontmatter: {path}")
                lines: list[bytes] = []
                total = len(first)
                while True:
                    line = file.readline()
                    if not line:
                        raise SkillFormatError(f"unterminated YAML frontmatter: {path}")
                    total += len(line)
                    if total > self.max_frontmatter_bytes:
                        raise SkillFormatError(
                            "skill frontmatter exceeds "
                            f"max_frontmatter_bytes={self.max_frontmatter_bytes}"
                        )
                    if line.rstrip(b"\r\n") == b"---":
                        return b"".join(lines).decode("utf-8", errors="strict"), file.tell()
                    lines.append(line)
        except UnicodeDecodeError as exc:
            raise SkillFormatError(f"skill frontmatter must be UTF-8: {path}") from exc
        except OSError as exc:
            raise SkillFormatError(f"failed to read skill frontmatter: {exc}") from exc

    @staticmethod
    def _resolve_within(root: Path, candidate: Path) -> Path:
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
        if not resolved_candidate.is_relative_to(resolved_root):
            raise SkillFormatError(f"skill path escapes root: {candidate}")
        return resolved_candidate


class SkillRegistry:
    """Discover SKILL.md metadata without loading skill bodies."""

    def __init__(self, root: Path, parser: SkillParser | None = None) -> None:
        self.root = root  # 保存 Skill 目录集合的根路径。
        self.parser = parser or SkillParser()  # 负责 frontmatter 和正文的分阶段解析。
        self._descriptors: dict[str, SkillDescriptor] | None = None  # 延迟构建的 metadata 索引。

    def list_metadata(self) -> list[SkillMetadata]:
        return [descriptor.metadata for descriptor in self._discover().values()]

    def get_descriptor(self, name: str) -> SkillDescriptor:
        try:
            return self._discover()[name]
        except KeyError as exc:
            raise KeyError(f"Skill not found: {name}") from exc

    def load(self, name: str) -> LoadedSkill:
        return self.parser.load_content(self.get_descriptor(name))

    def _discover(self) -> dict[str, SkillDescriptor]:
        if self._descriptors is not None:
            return self._descriptors
        descriptors: dict[str, SkillDescriptor] = {}
        if self.root.exists():
            for path in sorted(self.root.glob("*/SKILL.md")):
                descriptor = self.parser.parse_metadata(path, self.root)
                name = descriptor.metadata.name
                if name in descriptors:
                    raise SkillFormatError(f"duplicate skill name: {name}")
                descriptors[name] = descriptor
        self._descriptors = dict(sorted(descriptors.items()))
        return self._descriptors
