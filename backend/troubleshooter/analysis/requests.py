"""Deterministic facts: these remain available even if a model is unavailable."""

from troubleshooter.domain.models import Event

from .ordering import time_key


def _new_call(event: Event) -> dict:
    return {
        "id": event.id,
        "service": event.service,
        "api": event.api,
        "method": event.method,
        "direction": event.direction,
        "peer_service": event.peer_service,
        "call_id": event.call_id,
        "attempt": event.attempt,
        "evidence_ids": [],
        "request_ids": [],
        "response_ids": [],
    }


def _merge_event(call: dict, event: Event) -> None:
    call["evidence_ids"].append(event.id)
    call[f"{event.kind}_ids"].append(event.id)
    if not call["api"]:
        call["api"] = event.api
    if not call["method"]:
        call["method"] = event.method
    if call["direction"] == "unknown" and event.direction != "unknown":
        call["direction"] = event.direction
    if not call["peer_service"]:
        call["peer_service"] = event.peer_service


def _orphan_call(event: Event) -> dict:
    return {
        "id": event.id,
        "service": event.service,
        "api": event.api,
        "method": event.method,
        "direction": event.direction,
        "peer_service": event.peer_service,
        "evidence_ids": [event.id],
        "request_ids": [event.id] if event.kind == "request" else [],
        "response_ids": [event.id] if event.kind == "response" else [],
        "pairing": "unknown",
    }


def _add_pairing_status(call: dict) -> None:
    call["missing_response"] = bool(call["request_ids"] and not call["response_ids"])
    call["pairing_ambiguous"] = (
        len(call["request_ids"]) > 1 or len(call["response_ids"]) > 1
    )


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
            call = calls.get(key)
            if call is None:
                call = _new_call(event)
                calls[key] = call
            _merge_event(call, event)
        else:
            orphans.append(_orphan_call(event))
    nodes = list(calls.values()) + orphans
    for node in nodes:
        _add_pairing_status(node)
    return {"calls": nodes}
