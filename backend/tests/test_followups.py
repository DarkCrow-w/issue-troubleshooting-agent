import asyncio

from troubleshooter.domain.models import InvestigationRequest
from troubleshooter.investigation.followups import FollowupPlanner
from troubleshooter.investigation.graph import build_graph


class _Models:
    def __init__(self):
        self.skills = []

    def finish_skill(self, state):
        return state


def _graph_nodes(request: InvestigationRequest) -> set[str]:
    graph = build_graph(
        request=request,
        config={},
        skills=[],
        budget=object(),
        collector=object(),
        planner=object(),
        models=_Models(),
        progress=lambda _message: None,
    )
    return set(graph.get_graph().nodes)


def test_followup_is_disabled_by_default():
    """即使工作流包含补查 skill，用户未开启时也不能继续查询 Splunk。"""
    request = InvestigationRequest(correlation_id="trace-001", environment="sit")
    planner = FollowupPlanner(
        request=request,
        skill=object(),  # 提前返回，不应读取 skill、模型或预算。
        model=object(),
        budget=object(),
    )

    result = asyncio.run(planner.plan({}))

    assert request.followup_enabled is False
    assert result == {"next_query": None}


def test_langgraph_only_adds_followup_node_when_user_enables_it():
    default_request = InvestigationRequest(correlation_id="trace-001", environment="sit")
    enabled_request = default_request.model_copy(update={"followup_enabled": True})

    assert "plan_followup" not in _graph_nodes(default_request)
    assert "plan_followup" in _graph_nodes(enabled_request)
