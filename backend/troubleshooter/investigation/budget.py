"""One place to account for every query, follow-up and model invocation."""

from troubleshooter.config.settings import Settings
from troubleshooter.domain.errors import BudgetExceeded
from troubleshooter.domain.models import Usage


def estimate_tokens(text: str) -> int:
    """Portable UTF-8 byte upper bound, not the provider's billable token count."""
    return len(text.encode("utf-8"))


class RunBudget:
    def __init__(self, settings: Settings, usage: Usage | None = None):
        self.settings = settings
        self.usage = usage or Usage()

    @property
    def input_limit(self) -> int:
        return min(
            self.settings.max_input_tokens,
            self.settings.llm_context_tokens - self.settings.llm_max_output_tokens,
        )

    @property
    def remaining_logs(self) -> tuple[int, int]:
        return (
            max(0, self.settings.max_events - self.usage.events),
            max(0, self.settings.max_bytes - self.usage.bytes_read),
        )

    @property
    def can_followup(self) -> bool:
        return self.usage.followups < self.settings.max_followups and all(self.remaining_logs)

    def record_query(self, count: int, size: int):
        self.usage.queries += 1
        self.usage.events += count
        self.usage.bytes_read += size

    def reserve_model_call(self, input_tokens: int):
        if input_tokens > self.input_limit:
            raise BudgetExceeded("模型输入超过预算，当前分析未执行")
        if self.usage.model_calls >= self.settings.max_model_calls:
            raise BudgetExceeded("模型调用预算已耗尽")
        self.usage.model_calls += 1
        self.usage.estimated_input_tokens += input_tokens

    def record_model_usage(self, usage: dict):
        self.usage.prompt_tokens += int(usage.get("input_tokens", 0))
        self.usage.completion_tokens += int(usage.get("output_tokens", 0))
