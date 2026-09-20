"""Splunk and local replay implement the same bounded search interface."""

import json
from datetime import datetime
from pathlib import Path

from troubleshooter.domain.models import QuerySpec, SearchResult
from troubleshooter.logs.normalization import normalize

from .query import build_spl


class ReplaySource:
    def __init__(self, path: Path, config: dict):
        self.path = path
        self.config = config

    async def search(self, query: QuerySpec, max_events: int, max_bytes: int) -> SearchResult:
        content = self.path.read_text()
        try:
            payload = json.loads(content)
            records = payload.get("results", []) if isinstance(payload, dict) else payload
        except json.JSONDecodeError:
            records = [json.loads(line) for line in content.splitlines() if line.strip()]
        result = SearchResult(query=build_spl(query, self.config), sid="replay")
        for wrapper in records:
            if wrapper.get("preview") is True:
                continue
            record = wrapper.get("result", wrapper)
            event = normalize(record, self.config)
            try:
                when = datetime.fromisoformat(event.timestamp)
                in_window = query.start_time <= when <= query.end_time
            except (ValueError, TypeError):
                in_window = False
            if not in_window:
                continue
            if query.identifier and query.identifier not in event.correlation_ids + list(
                event.ids.values()
            ):
                continue
            if query.service and event.service != query.service:
                continue
            if query.instance and event.instance != query.instance:
                continue
            size = len(json.dumps(record).encode())
            if len(result.records) >= max_events or result.bytes_read + size > max_bytes:
                result.warnings.append("日志预算已耗尽，结果不完整")
                break
            result.records.append(record)
            result.bytes_read += size
        return result
