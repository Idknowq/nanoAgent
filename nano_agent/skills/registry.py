from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class Skill(BaseModel):
    """一个 Markdown skill 的结构化表示。"""

    name: str  # skill 名称，默认来自文件名。
    description: str  # skill 的简短说明，当前取 Markdown 第一行。
    path: Path  # skill 文件在本机的路径。
    content: str  # skill Markdown 完整内容。


class SkillRegistry:
    """从目录加载 Markdown skill。"""

    def __init__(self, root: Path) -> None:
        self.root = root  # 保存 skill 文件所在目录。

    def list_skills(self) -> list[Skill]:
        if not self.root.exists():
            return []
        skills: list[Skill] = []
        for path in sorted(self.root.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            skills.append(
                Skill(
                    name=path.stem,
                    description=content.splitlines()[0] if content else "",
                    path=path,
                    content=content,
                )
            )
        return skills
