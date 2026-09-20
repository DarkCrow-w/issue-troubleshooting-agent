"""Model steps return state updates; LangGraph controls chunk and skill iteration."""

from troubleshooter.domain.errors import ModelUnavailable
from troubleshooter.domain.models import InvestigationRequest, ModelDiagnosis
from troubleshooter.models import ModelCallInterface
from troubleshooter.skills import Skill

from .state import InvestigationState


class ModelSteps:
    def __init__(
        self,
        request: InvestigationRequest,
        skills: list[Skill],
        model: ModelCallInterface,
    ):
        self.skills = [s for s in skills if s.kind in ("llm", "report")]
        self.model = model
        self.enabled = model.enabled
        self.question = request.question

    async def analyse_chunk(self, state: InvestigationState) -> dict:
        skill = self.skills[state["skill_index"]]
        chunk = state["chunks"][state["chunk_index"]]
        warnings = list(state["warnings"])
        try:
            result = await self.model.analyze_evidence_chunk(
                skill.prompt,
                self.question,
                chunk,
                state["artifacts"],
                set(state["events"]),
            )
            result = await self._expand_evidence(skill, result, state, warnings)
            return {
                "skill_results": state["skill_results"] + [result],
                "chunk_index": state["chunk_index"] + 1,
                "warnings": warnings,
            }
        except ModelUnavailable as exc:
            return {"warnings": warnings + [str(exc)], "skill_failed": True}

    async def _expand_evidence(
        self, skill: Skill, result: ModelDiagnosis, state: InvestigationState, warnings: list[str]
    ) -> ModelDiagnosis:
        if not result.evidence_requests:
            return result
        if "read_evidence" not in skill.tools:
            warnings.append(f"skill {skill.id} 未获准读取完整证据")
            return result
        expanded = [
            {"event_id": event_id, "record": state["records"][event_id]}
            for event_id in result.evidence_requests
        ]
        try:
            result = await self.model.analyze_expanded_evidence(
                skill.prompt,
                self.question,
                result,
                expanded,
                set(state["events"]),
            )
            if result.evidence_requests:
                warnings.append("单个 skill 分块的证据展开轮次已耗尽")
        except ModelUnavailable as exc:
            warnings.append(str(exc) + "；完整证据未完成模型分析")
        return result

    async def finish_skill(self, state: InvestigationState) -> dict:
        skill = self.skills[state["skill_index"]]
        results = state["skill_results"]
        update = {
            "skill_index": state["skill_index"] + 1,
            "chunk_index": 0,
            "skill_results": [],
            "skill_failed": False,
        }
        if skill.kind == "llm":
            update["artifacts"] = {
                **state["artifacts"],
                skill.id: [r.model_dump() for r in results],
            }
            return update
        update["diagnoses"] = results
        if len(results) > 1:
            custom_ids = {s.id for s in self.skills if s.kind == "llm"}
            try:
                synthesis = await self.model.synthesize_report(
                    skill.prompt,
                    self.question,
                    results,
                    {key: value for key, value in state["artifacts"].items() if key in custom_ids},
                    set(state["events"]),
                )
                update["diagnoses"] = [synthesis]
            except ModelUnavailable as exc:
                update["warnings"] = state["warnings"] + [
                    str(exc) + "；保留各分块分析，未完成全局综合"
                ]
        return update
