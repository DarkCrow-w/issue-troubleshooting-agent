"""Splunk and local replay implement the same bounded search interface."""

import json
import re
from datetime import datetime
from pathlib import Path

from troubleshooter.domain.models import QuerySpec, SearchResult
from troubleshooter.logs.normalization import normalize

from .query import build_spl, validate_spl


def replay_identifier(spl: str, correlation_fields: list[str]) -> str:
    """让本地 Demo 支持最常用的 ``correlationId=...`` 精确 SPL 条件。"""

    search_filter, _ = validate_spl(spl)
    for field in correlation_fields:
        pattern = rf'\b{re.escape(field)}\s*=\s*(?:"((?:\\.|[^"])*)"|([\w.:/-]+))'
        match = re.search(pattern, search_filter)
        if not match:
            continue
        value = match.group(1) or match.group(2)
        return value.replace('\\"', '"').replace("\\\\", "\\")
    return ""


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
        custom_identifier = replay_identifier(query.spl, self.config["correlation_fields"])
        if query.spl:
            result.warnings.append("回放模式仅模拟 SPL 中的精确关联 ID 条件，不执行完整管道语义")
        for wrapper in records:
            if wrapper.get("preview") is True:
                continue
            record = wrapper.get("result", wrapper)
            event = normalize(record, self.config)
            try:
                when = datetime.fromisoformat(event.timestamp)
                after_start = not query.start_time or when >= query.start_time
                before_end = not query.end_time or when <= query.end_time
                in_window = after_start and before_end
            except (ValueError, TypeError):
                in_window = not query.start_time and not query.end_time
            if not in_window:
                continue
            if query.identifier and query.identifier not in event.correlation_ids + list(
                event.ids.values()
            ):
                continue
            if custom_identifier and custom_identifier not in event.correlation_ids + list(
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
