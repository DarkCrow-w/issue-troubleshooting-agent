from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class InvestigationRequest(BaseModel):
    correlation_id: str = Field(default="", max_length=256)
    spl: str = Field(default="", max_length=10_000)
    environment: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    cleaning_enabled: bool = True
    followup_enabled: bool = False
    workflow: str = "standard"
    question: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid_window(self):
        supplied_times = [value for value in (self.start_time, self.end_time) if value]
        if any(value.tzinfo is None for value in supplied_times):
            raise ValueError("已填写的时间必须包含时区")
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("结束时间必须晚于开始时间")
        self.correlation_id = self.correlation_id.strip()
        self.spl = self.spl.strip()
        if not self.correlation_id and not self.spl:
            raise ValueError("关联 ID 和 Splunk SPL 至少填写一个")
        if any(ord(char) < 32 for char in self.correlation_id):
            raise ValueError("关联 ID 不得包含控制字符")
        return self


class Event(BaseModel):
    id: str
    timestamp: str
    scope: str = "transaction"
    service: str
    instance: str = ""
    ids: dict[str, str] = Field(default_factory=dict)
    correlation_ids: list[str] = Field(default_factory=list)
    api: str = ""
    method: str = ""
    direction: str = "unknown"
    kind: str = "log"
    level: str = ""
    message: str = ""
    request: Any = None
    response: Any = None
    http_status: int | None = None
    business_code: str | None = None
    exception: dict[str, Any] | None = None
    peer_service: str = ""
    call_id: str = ""
    parent_call_id: str = ""
    attempt: str = ""
    source: dict[str, Any] = Field(default_factory=dict)
    parse_warnings: list[str] = Field(default_factory=list)


class EvidenceClaim(BaseModel):
    statement: str
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"] = "low"


class Hypothesis(EvidenceClaim):
    counter_evidence_ids: list[str] = Field(default_factory=list)
    verification: str = ""


class ModelDiagnosis(BaseModel):
    evidence_requests: list[str] = Field(default_factory=list, max_length=3)
    summary: str
    findings: list[EvidenceClaim] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class FollowupProposal(BaseModel):
    kind: Literal["identifier", "context"]
    evidence_id: str
    identifier: str = ""
    reason: str = Field(min_length=1, max_length=500)


class QuerySpec(BaseModel):
    environment: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    identifier: str = ""
    spl: str = ""
    service: str = ""
    instance: str = ""
    reason: str = "首次关联 ID 查询"
    evidence_id: str = ""


class SearchResult(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    query: str = ""
    sid: str = ""
    bytes_read: int = 0


class Usage(BaseModel):
    queries: int = 0
    followups: int = 0
    events: int = 0
    bytes_read: int = 0
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_input_tokens: int = 0
    before_chars: int = 0
    after_chars: int = 0
