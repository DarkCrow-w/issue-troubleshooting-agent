"""业务层唯一的模型调用入口。

更换公司内部模型网关时，优先修改本目录中的 ``client.py``；如果输入协议也变化，
只需要同步调整本文件，不应把供应商调用细节放回 investigation 目录。
"""

from typing import Protocol

from pydantic import BaseModel, Field

from troubleshooter.config.settings import Settings
from troubleshooter.domain.models import FollowupProposal, ModelDiagnosis
from troubleshooter.investigation.budget import RunBudget
from troubleshooter.skills.context import compact_artifacts

from .client import JsonModel, ModelClient


class FollowupPlan(BaseModel):
    """模型补查输出，仅在 models module 内使用。"""

    proposals: list[FollowupProposal] = Field(default_factory=list, max_length=3)


class ModelCallInterface(Protocol):
    """调查流程可见的稳定 interface；调用方不接触模型 SDK 与输出 parser。"""

    enabled: bool

    async def propose_followups(
        self,
        prompt: str,
        events: list[dict],
        already_searched: set[str],
        valid_ids: set[str],
    ) -> list[FollowupProposal]: ...

    async def analyze_evidence_chunk(
        self,
        prompt: str,
        question: str,
        events: list[dict],
        artifacts: dict,
        valid_ids: set[str],
    ) -> ModelDiagnosis: ...

    async def analyze_expanded_evidence(
        self,
        prompt: str,
        question: str,
        analysis: ModelDiagnosis,
        requested_evidence: list[dict],
        valid_ids: set[str],
    ) -> ModelDiagnosis: ...

    async def synthesize_report(
        self,
        prompt: str,
        question: str,
        partial_analyses: list[ModelDiagnosis],
        skill_artifacts: dict,
        valid_ids: set[str],
    ) -> ModelDiagnosis: ...

    async def close(self) -> None: ...


class ModelCalls:
    """把每一种业务模型调用包装成命名方法，并统一委托给底层 adapter。"""

    def __init__(
        self,
        settings: Settings,
        budget: RunBudget,
        client: JsonModel | None = None,
    ):
        self.enabled = settings.model_mode != "offline"
        self.client = client or ModelClient(settings, budget)

    async def propose_followups(
        self,
        prompt: str,
        events: list[dict],
        already_searched: set[str],
        valid_ids: set[str],
    ) -> list[FollowupProposal]:
        result = await self.client.generate(
            prompt,
            {"events": events, "already_searched": sorted(already_searched)},
            FollowupPlan,
            valid_ids,
        )
        return result.proposals

    async def analyze_evidence_chunk(
        self,
        prompt: str,
        question: str,
        events: list[dict],
        artifacts: dict,
        valid_ids: set[str],
    ) -> ModelDiagnosis:
        return await self.client.generate(
            prompt,
            {
                "question": question,
                "events": events,
                "prior_skill_artifacts": compact_artifacts(artifacts),
                "instructions": "这是证据分块，仅分析该块，不要假定其他块不存在。",
            },
            ModelDiagnosis,
            valid_ids,
        )

    async def analyze_expanded_evidence(
        self,
        prompt: str,
        question: str,
        analysis: ModelDiagnosis,
        requested_evidence: list[dict],
        valid_ids: set[str],
    ) -> ModelDiagnosis:
        return await self.client.generate(
            prompt,
            {
                "question": question,
                "analysis": analysis.model_dump(),
                "requested_evidence": requested_evidence,
                "instructions": "已提供请求的完整原始证据，请完成分析，不再请求证据。",
            },
            ModelDiagnosis,
            valid_ids,
        )

    async def synthesize_report(
        self,
        prompt: str,
        question: str,
        partial_analyses: list[ModelDiagnosis],
        skill_artifacts: dict,
        valid_ids: set[str],
    ) -> ModelDiagnosis:
        return await self.client.generate(
            prompt,
            {
                "question": question,
                "partial_analyses": [item.model_dump() for item in partial_analyses],
                "skill_artifacts": skill_artifacts,
            },
            ModelDiagnosis,
            valid_ids,
        )

    async def close(self) -> None:
        close = getattr(self.client, "aclose", None)
        if close:
            await close()


def create_model_calls(settings: Settings, budget: RunBudget) -> ModelCalls:
    """默认工厂单独命名，方便在 composition root 或测试中整体替换。"""

    return ModelCalls(settings, budget)
