from __future__ import annotations

from nano_agent.skills.registry import LoadedSkill, SkillRegistry


class SkillSession:
    """Track skills activated during one Agent run."""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry  # 当前 run 可发现和加载的 Skill 注册表。
        self._activated: dict[str, LoadedSkill] = {}  # 已加载正文的 Skill 索引。

    def activate(self, name: str) -> tuple[LoadedSkill, bool]:
        if name in self._activated:
            return self._activated[name], False
        loaded = self.registry.load(name)
        self._activated[name] = loaded
        return loaded, True

    def get(self, name: str) -> LoadedSkill:
        try:
            return self._activated[name]
        except KeyError as exc:
            raise KeyError(f"Skill is not activated: {name}") from exc

    @property
    def activated_names(self) -> list[str]:
        return sorted(self._activated)
