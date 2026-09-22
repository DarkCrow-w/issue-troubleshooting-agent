import hashlib
from pathlib import Path

import yaml

from troubleshooter.analysis import HANDLERS

from .definition import Skill


class SkillRegistry:
    def __init__(self, directory: Path, config: dict):
        self.skills: dict[str, Skill] = {}
        self.config = config
        for manifest in sorted(directory.glob("*/skill.yaml")):
            skill = self._load(manifest)
            self._validate_skill(skill)
            self.skills[skill.id] = skill
        for name in config["workflows"]:
            self.workflow(name)

    @staticmethod
    def _load(manifest: Path) -> Skill:
        manifest_text = manifest.read_text()
        prompt_file = manifest.with_name("prompt.md")
        prompt = prompt_file.read_text() if prompt_file.exists() else ""
        return Skill(
            **yaml.safe_load(manifest_text),
            prompt=prompt,
            digest=hashlib.sha256((manifest_text + prompt).encode()).hexdigest(),
        )

    def _validate_skill(self, skill: Skill) -> None:
        if skill.id in self.skills:
            raise ValueError(f"重复 skill：{skill.id}")
        if skill.kind == "code" and skill.handler not in HANDLERS:
            raise ValueError(f"未注册的可信处理器：{skill.handler}")
        allowed_tools = {"read_evidence", "propose_followup"}
        if set(skill.tools) - allowed_tools:
            raise ValueError(f"skill {skill.id} 包含不允许的工具")
        if skill.kind == "llm" and skill.output != "evidence-claims":
            raise ValueError("自定义 LLM skill 的输出必须为 evidence-claims")

    def _visit(
        self,
        skill_id: str,
        selected: set[str],
        visited: set[str],
        visiting: set[str],
        ordered: list[Skill],
    ) -> None:
        if skill_id in visiting:
            raise ValueError("skill 依赖存在循环")
        if skill_id in visited:
            return
        if skill_id not in self.skills or skill_id not in selected:
            raise ValueError(f"workflow 缺少 skill 或依赖：{skill_id}")

        visiting.add(skill_id)
        for dependency in self.skills[skill_id].depends_on:
            self._visit(dependency, selected, visited, visiting, ordered)
        visiting.remove(skill_id)
        visited.add(skill_id)
        ordered.append(self.skills[skill_id])

    def _ordered_skills(self, skill_ids: list[str]) -> list[Skill]:
        selected = set(skill_ids)
        visited: set[str] = set()
        visiting: set[str] = set()
        ordered: list[Skill] = []
        for skill_id in skill_ids:
            self._visit(skill_id, selected, visited, visiting, ordered)
        return ordered

    def _validate_workflow(self, ordered: list[Skill]) -> None:
        if sum(skill.kind == "report" for skill in ordered) != 1:
            raise ValueError("workflow 必须恰好包含一个报告 skill")
        if ordered[-1].kind != "report":
            raise ValueError("报告 skill 必须是 workflow 的最后一步")
        if sum(skill.kind == "followup" for skill in ordered) > 1:
            raise ValueError("每个 workflow 最多包含一个补查 skill")
        for skill in ordered:
            if skill.kind in ("code", "followup") and any(
                self.skills[dependency].kind != "code"
                for dependency in skill.depends_on
            ):
                raise ValueError("规则提取和补查只能依赖前序代码 skill")

    def workflow(self, name: str) -> list[Skill]:
        if name not in self.config["workflows"]:
            raise ValueError("未知 workflow")
        selected = self.config["workflows"][name]["skills"]
        if len(selected) != len(set(selected)):
            raise ValueError("workflow 含重复 skill")
        ordered = self._ordered_skills(selected)
        self._validate_workflow(ordered)
        return ordered
