"""识别一次 API 调用中的请求、响应和响应后处理阶段。"""

from troubleshooter.domain.models import Event

from .ordering import time_key

PHASE_LABELS = {
    "request": "请求发送",
    "request_processing": "请求处理",
    "response": "响应返回",
    "response_processing": "响应后处理",
    "unknown": "未知阶段",
}


def _event_phase(event: Event, response_times: list[float]) -> str:
    """只根据明确的事件类型和先后顺序判断阶段，不猜测业务字段。"""
    if event.kind == "request":
        return "request"
    if event.kind == "response":
        return "response"
    if not response_times:
        return "request_processing"

    event_time = time_key(event)[0]
    if event_time == float("inf"):
        return "unknown"
    if min(response_times) <= event_time:
        return "response_processing"
    return "request_processing"


def _phase(status: str, evidence_ids: list[str]) -> dict:
    return {"status": status, "evidence_ids": list(dict.fromkeys(evidence_ids))}


def analyze_call_lifecycle(
    node: dict,
    events_by_id: dict[str, Event],
    failure_by_event: dict[str, dict],
) -> dict:
    """返回 UI 可直接使用的三阶段状态，以及最早失败所属阶段。"""
    request_ids = list(node.get("request_ids", []))
    response_ids = list(node.get("response_ids", []))
    evidence_ids = list(node.get("evidence_ids", []))
    response_times = [
        time_key(events_by_id[event_id])[0]
        for event_id in response_ids
        if event_id in events_by_id
    ]

    failures = []
    for event_id in evidence_ids:
        event = events_by_id.get(event_id)
        failure = failure_by_event.get(event_id)
        if event and failure:
            failures.append((event, failure, _event_phase(event, response_times)))
    failures.sort(key=lambda item: time_key(item[0]))

    failed_ids: dict[str, list[str]] = {
        "request": [],
        "request_processing": [],
        "response": [],
        "response_processing": [],
        "unknown": [],
    }
    reasons = []
    for event, failure, event_phase in failures:
        failed_ids[event_phase].append(event.id)
        reasons.extend(failure["reasons"])

    request_status = "failed" if failed_ids["request"] else "unknown"
    if request_ids and request_status != "failed":
        request_status = "success"

    request_processing_status = (
        "failed" if failed_ids["request_processing"] else "unknown"
    )
    if response_ids and request_processing_status != "failed":
        request_processing_status = "success"

    response_status = "failed" if failed_ids["response"] else "unknown"
    if response_ids and response_status != "failed":
        response_status = "success"
    elif node.get("missing_response"):
        response_status = "warning"

    processing_status = "failed" if failed_ids["response_processing"] else "unknown"
    if failed_ids["unknown"] and processing_status != "failed":
        processing_status = "warning"
    if response_ids and processing_status != "failed":
        processing_status = "warning" if failed_ids["unknown"] else "success"

    first_failure_phase = failures[0][2] if failures else ""
    status = "failed" if failures else "unknown"
    if not failures and (node.get("missing_response") or node.get("pairing_ambiguous")):
        status = "warning"
    elif not failures and response_ids:
        status = "success"

    return {
        "status": status,
        "failure_reasons": list(dict.fromkeys(reasons)),
        "failure_phase": first_failure_phase,
        "failure_phase_label": PHASE_LABELS.get(first_failure_phase, ""),
        "phases": {
            "request": _phase(
                request_status,
                request_ids + failed_ids["request"],
            ),
            "request_processing": _phase(
                request_processing_status,
                failed_ids["request_processing"],
            ),
            "response": _phase(
                response_status,
                response_ids + failed_ids["response"],
            ),
            "response_processing": _phase(
                processing_status,
                failed_ids["response_processing"] + failed_ids["unknown"],
            ),
        },
    }
