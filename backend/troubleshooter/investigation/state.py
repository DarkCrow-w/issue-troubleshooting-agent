"""Business state flowing through LangGraph; no credentials or service handles."""

from typing import TypedDict

from troubleshooter.domain.models import (
    Event,
    FollowupProposal,
    InvestigationRequest,
    ModelDiagnosis,
    QuerySpec,
)


class InvestigationState(TypedDict):
    events: dict[str, Event]
    records: dict[str, dict]
    artifacts: dict
    queries: list[dict]
    warnings: list[str]
    notes: list[str]
    diagnoses: list[ModelDiagnosis]
    next_query: QuerySpec | None
    searched: set[str]
    context_searched: set[str]
    proposals: list[FollowupProposal]
    model_planned: bool
    chunks: list[list[dict]]
    skill_index: int
    chunk_index: int
    skill_results: list[ModelDiagnosis]
    skill_failed: bool
    report: dict


def initial_state(request: InvestigationRequest) -> InvestigationState:
    return InvestigationState(
        events={},
        records={},
        artifacts={},
        queries=[],
        warnings=[],
        notes=[],
        diagnoses=[],
        next_query=QuerySpec(
            environment=request.environment,
            start_time=request.start_time,
            end_time=request.end_time,
            identifier=request.correlation_id,
        ),
        searched={request.correlation_id},
        context_searched=set(),
        model_planned=False,
        proposals=[],
        chunks=[],
        skill_index=0,
        chunk_index=0,
        skill_results=[],
        skill_failed=False,
        report={},
    )
