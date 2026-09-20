"""Deterministic facts: these remain available even if a model is unavailable."""

from troubleshooter.domain.models import Event

from .ordering import time_key


def request_response(events: list[Event], config: dict, artifacts: dict) -> dict:
    calls: dict[tuple, dict] = {}
    orphans = []
    for event in sorted(events, key=time_key):
        if event.kind not in ("request", "response"):
            continue
        # Without an explicit call/span ID, pairing by time alone would invent causality.
        # direction 描述日志观察方向，同一调用的请求和响应可能分别是 outbound/inbound。
        # 调用 ID、实例和重试次数已经足够隔离，不能再用 direction 拆开一对消息。
        key = (event.service, event.instance, event.call_id, event.attempt)
        if event.call_id:
            call = calls.setdefault(
                key,
                {
                    "id": event.id,
                    "service": event.service,
                    "api": event.api,
                    "call_id": event.call_id,
                    "attempt": event.attempt,
                    "evidence_ids": [],
                    "request_ids": [],
                    "response_ids": [],
                },
            )
            call["evidence_ids"].append(event.id)
            call[f"{event.kind}_ids"].append(event.id)
            if not call["api"]:
                call["api"] = event.api
        else:
            orphans.append(
                {
                    "id": event.id,
                    "service": event.service,
                    "api": event.api,
                    "evidence_ids": [event.id],
                    "request_ids": [event.id] if event.kind == "request" else [],
                    "response_ids": [event.id] if event.kind == "response" else [],
                    "pairing": "unknown",
                }
            )
    nodes = list(calls.values()) + orphans
    for node in nodes:
        node["missing_response"] = bool(node["request_ids"] and not node["response_ids"])
        node["pairing_ambiguous"] = len(node["request_ids"]) > 1 or len(node["response_ids"]) > 1
    return {"calls": nodes}
