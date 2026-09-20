"""Retrieve, normalize and attribute evidence; retain the original record."""

from collections import Counter
from time import monotonic

from troubleshooter.logs.normalization import normalize
from troubleshooter.logs.sources import LogSource
from troubleshooter.observability.logging import log_event
from troubleshooter.persistence.postgres import Store

from .budget import RunBudget
from .state import InvestigationState


class EvidenceCollector:
    def __init__(
        self,
        source: LogSource,
        store: Store,
        config: dict,
        budget: RunBudget,
        task_id: str,
    ):
        self.source, self.store = source, store
        self.config, self.budget, self.task_id = config, budget, task_id

    async def collect(self, state: InvestigationState) -> dict:
        query = state["next_query"]
        remaining_events, remaining_bytes = self.budget.remaining_logs
        if not query or not remaining_events or not remaining_bytes:
            return {"warnings": state["warnings"] + ["日志获取预算耗尽，未执行剩余查询"]}
        started = monotonic()
        log_event("query.started", query_number=self.budget.usage.queries + 1)
        result = await self.source.search(query, remaining_events, remaining_bytes)
        self.budget.record_query(len(result.records), result.bytes_read)
        events, records = dict(state["events"]), dict(state["records"])
        warnings = state["warnings"] + result.warnings
        occurrences: Counter[str] = Counter()
        transaction_ids = {
            value
            for e in events.values()
            if e.scope == "transaction"
            for value in e.correlation_ids
        }
        # 保留 Splunk 原始记录；上下文日志只有确认关联后才能升级为本交易证据。
        for original in result.records:
            record = original
            event = normalize(record, self.config)
            occurrences[event.id] += 1
            # 没有 Splunk 唯一位置时，用出现次数区分内容相同的独立调用。
            if not record.get("_cd") and occurrences[event.id] > 1:
                event.id = f"{event.id}_{occurrences[event.id]}"
            if query.identifier and query.identifier not in event.correlation_ids + list(
                event.ids.values()
            ):
                warnings.append("存在无法确认交易归属的检索结果，已排除；可补充关联字段解析规则")
                continue
            if not query.identifier and not transaction_ids.intersection(event.correlation_ids):
                event.scope = "context"
            previous = events.get(event.id)
            if previous and (previous.scope == "transaction" or event.scope == "context"):
                continue
            events[event.id], records[event.id] = event, record
            self.store.save_evidence(
                self.task_id, event.id, {"event": event.model_dump(), "record": record}
            )
            warnings.extend(event.parse_warnings)
        log_event(
            "query.completed",
            count=len(result.records),
            bytes_read=result.bytes_read,
            warning_count=len(warnings) - len(state["warnings"]),
            duration_ms=round((monotonic() - started) * 1000),
        )
        entry = {
            **query.model_dump(mode="json"),
            "spl": result.query,
            "sid": result.sid,
            "count": len(result.records),
            "warnings": result.warnings,
        }
        return {
            "events": events,
            "records": records,
            "warnings": warnings,
            "queries": state["queries"] + [entry],
            "next_query": None,
        }
