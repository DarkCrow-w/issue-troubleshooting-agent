"""Follow-up policy: models propose; code validates identity, scope and budgets."""

from datetime import datetime, timedelta

from troubleshooter.analysis import time_key
from troubleshooter.domain.errors import ModelUnavailable
from troubleshooter.domain.models import FollowupProposal, InvestigationRequest, QuerySpec
from troubleshooter.models import ModelCallInterface
from troubleshooter.skills import Skill

from .budget import RunBudget
from .state import InvestigationState


def validate_proposal(
    proposal: FollowupProposal, state: InvestigationState, request: InvestigationRequest
) -> QuerySpec | None:
    # 模型只提出建议；关联 ID 必须真实出现在已确认归属的证据中。
    event = state["events"].get(proposal.evidence_id)
    if not event or event.scope != "transaction":
        return None
    query = QuerySpec(
        environment=request.environment,
        start_time=request.start_time,
        end_time=request.end_time,
        reason=proposal.reason,
        evidence_id=event.id,
    )
    if proposal.kind == "identifier":
        if not proposal.identifier or proposal.identifier in state["searched"]:
            return None
        if proposal.identifier not in list(event.ids.values()) + event.correlation_ids:
            return None
        query.identifier = proposal.identifier
    else:
        if (
            not event.instance
            or event.service == "unknown"
            or event.id in state["context_searched"]
        ):
            return None
        # 上下文补查必须收窄到同实例附近；用户填写时间时再应用上下界。
        try:
            timestamp = datetime.fromisoformat(event.timestamp)
            context_start = timestamp - timedelta(seconds=2)
            context_end = timestamp + timedelta(seconds=2)
            query.start_time = (
                max(request.start_time, context_start) if request.start_time else context_start
            )
            query.end_time = min(request.end_time, context_end) if request.end_time else context_end
        except (ValueError, TypeError):
            return None
        query.service, query.instance = event.service, event.instance
    return query


def rule_proposals(state: InvestigationState) -> list[FollowupProposal]:
    candidates = []
    for event in sorted(state["events"].values(), key=time_key):
        if event.scope != "transaction":
            continue
        for key in ("correlationId", "x_request_id", "contextId", "businessSequence"):
            value = event.ids.get(key)
            if value and value not in state["searched"]:
                candidates.append(
                    FollowupProposal(
                        kind="identifier",
                        evidence_id=event.id,
                        identifier=value,
                        reason=f"沿事件中的 {key} 补查关联日志",
                    )
                )
        if event.exception and event.instance and event.id not in state["context_searched"]:
            candidates.append(
                FollowupProposal(
                    kind="context", evidence_id=event.id, reason="补齐异常前后同实例 2 秒上下文"
                )
            )
    return candidates


class FollowupPlanner:
    def __init__(
        self,
        request: InvestigationRequest,
        skill: Skill | None,
        model: ModelCallInterface,
        budget: RunBudget,
    ):
        self.request, self.skill, self.model, self.budget = request, skill, model, budget

    async def plan(self, state: InvestigationState) -> dict:
        if not self.skill or "propose_followup" not in self.skill.tools:
            return {"next_query": None}
        warnings = list(state["warnings"])
        proposals = list(state["proposals"])
        if not state["model_planned"] and state["events"] and self.model.enabled:
            compact = [
                {
                    "event_id": e.id,
                    "ids": e.ids,
                    "exception": bool(e.exception),
                    "service": e.service,
                }
                for e in list(state["events"].values())[:30]
            ]
            try:
                model_proposals = await self.model.propose_followups(
                    self.skill.prompt,
                    compact,
                    state["searched"],
                    set(state["events"]),
                )
                proposals.extend(model_proposals)
            except ModelUnavailable as exc:
                warnings.append(str(exc))
        # 模型建议校验不通过时，规则候选仍可执行；两者使用同一套预算和去重状态。
        proposals.extend(rule_proposals(state))
        update = {"model_planned": True, "warnings": warnings, "next_query": None, "proposals": []}
        for index, proposal in enumerate(proposals):
            query = validate_proposal(proposal, state, self.request)
            if query is None:
                continue
            if not self.budget.can_followup:
                update["notes"] = state["notes"] + ["补查达到配置预算；其余候选未执行"]
                return update
            self.budget.usage.followups += 1
            update.update(next_query=query, proposals=proposals[index + 1 :])
            if query.identifier:
                update["searched"] = state["searched"] | {query.identifier}
            else:
                update["context_searched"] = state["context_searched"] | {query.evidence_id}
            return update
        return update
