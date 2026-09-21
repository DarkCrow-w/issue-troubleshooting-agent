"""The investigation flow is explicit here; nodes contain no hidden orchestration loops."""

from collections.abc import Callable
from functools import partial

from langgraph.graph import END, START, StateGraph

from troubleshooter.domain.models import InvestigationRequest
from troubleshooter.reports.builder import build_report
from troubleshooter.skills import Skill
from troubleshooter.skills.execution import execute_code_skill

from .budget import RunBudget
from .evidence import EvidenceCollector
from .followups import FollowupPlanner
from .model_steps import ModelSteps
from .packing import prepare_chunks
from .state import InvestigationState


def build_graph(
    request: InvestigationRequest,
    config: dict,
    skills: list[Skill],
    budget: RunBudget,
    collector: EvidenceCollector,
    planner: FollowupPlanner,
    models: ModelSteps,
    progress: Callable[[str], None],
):
    builder = StateGraph(InvestigationState)

    async def retrieve(state):
        progress("查询交易日志")
        return await collector.collect(state)

    async def plan(state):
        progress("分析证据缺口并补查")
        return await planner.plan(state)

    def prepare(state):
        warnings, notes = list(state["warnings"]), list(state["notes"])
        if not state["events"]:
            warnings.append("指定范围内没有可确认归属的日志，无法判断交易成功或失败")
        return {
            "chunks": prepare_chunks(state, request, config, budget),
            "warnings": warnings,
            "notes": notes,
        }

    async def analyse(state):
        skill = models.skills[state["skill_index"]]
        progress(f"执行 {skill.id}：证据分块 {state['chunk_index'] + 1}/{len(state['chunks'])}")
        return await models.analyse_chunk(state)

    def after_prepare(state):
        return "analyse_chunk" if state["chunks"] else "report"

    def after_chunk(state):
        more = not state["skill_failed"] and state["chunk_index"] < len(state["chunks"])
        return "analyse_chunk" if more else "finish_skill"

    def after_skill(state):
        return "analyse_chunk" if state["skill_index"] < len(models.skills) else "report"

    builder.add_node("retrieve", retrieve)
    builder.add_edge(START, "retrieve")
    previous = "retrieve"
    for skill in skills:
        if skill.kind != "code":
            continue
        name = f"extract_{skill.id}"
        builder.add_node(name, partial(execute_code_skill, skill=skill, domain_config=config))
        builder.add_edge(previous, name)
        previous = name
    if request.followup_enabled:
        builder.add_node("plan_followup", plan)
        builder.add_edge(previous, "plan_followup")
        builder.add_conditional_edges(
            "plan_followup",
            lambda state: "retrieve" if state["next_query"] else "prepare_analysis",
            {"retrieve": "retrieve", "prepare_analysis": "prepare_analysis"},
        )
    else:
        builder.add_edge(previous, "prepare_analysis")
    builder.add_node("prepare_analysis", prepare)
    builder.add_conditional_edges(
        "prepare_analysis", after_prepare, {"analyse_chunk": "analyse_chunk", "report": "report"}
    )
    builder.add_node("analyse_chunk", analyse)
    builder.add_conditional_edges(
        "analyse_chunk",
        after_chunk,
        {"analyse_chunk": "analyse_chunk", "finish_skill": "finish_skill"},
    )
    builder.add_node("finish_skill", models.finish_skill)
    builder.add_conditional_edges(
        "finish_skill", after_skill, {"analyse_chunk": "analyse_chunk", "report": "report"}
    )
    builder.add_node("report", lambda state: {"report": build_report(state)})
    builder.add_edge("report", END)
    return builder.compile()
