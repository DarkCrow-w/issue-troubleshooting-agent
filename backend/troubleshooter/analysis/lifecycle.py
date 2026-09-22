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
FAILURE_PHASES = tuple(PHASE_LABELS)


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


def _failures(
    evidence_ids: list[str],
    events_by_id: dict[str, Event],
    failure_by_event: dict[str, dict],
    response_times: list[float],
) -> list[tuple[Event, dict, str]]:
    result = []
    for event_id in evidence_ids:
        event = events_by_id.get(event_id)
        failure = failure_by_event.get(event_id)
        if event and failure:
            result.append((event, failure, _event_phase(event, response_times)))
    return sorted(result, key=lambda item: time_key(item[0]))


def _group_failures(
    failures: list[tuple[Event, dict, str]],
) -> tuple[dict[str, list[str]], list[str]]:
    ids = {phase: [] for phase in FAILURE_PHASES}
    reasons = []
    for event, failure, phase in failures:
        ids[phase].append(event.id)
        reasons.extend(failure["reasons"])
    return ids, list(dict.fromkeys(reasons))


def _phase_status(failed_ids: list[str], observed_ids: list[str]) -> str:
    if failed_ids:
        return "failed"
    return "success" if observed_ids else "unknown"


def _response_status(
    failed_ids: list[str], response_ids: list[str], missing: bool
) -> str:
    status = _phase_status(failed_ids, response_ids)
    return "warning" if status == "unknown" and missing else status


def _response_processing_status(
    failed_ids: list[str], unknown_ids: list[str], response_ids: list[str]
) -> str:
    if failed_ids:
        return "failed"
    if unknown_ids:
        return "warning"
    return "success" if response_ids else "unknown"


def _call_status(failures: list, node: dict, response_ids: list[str]) -> str:
    if failures:
        return "failed"
    if node.get("missing_response") or node.get("pairing_ambiguous"):
        return "warning"
    return "success" if response_ids else "unknown"


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

    failures = _failures(evidence_ids, events_by_id, failure_by_event, response_times)
    failed_ids, reasons = _group_failures(failures)
    first_failure_phase = failures[0][2] if failures else ""

    return {
        "status": _call_status(failures, node, response_ids),
        "failure_reasons": reasons,
        "failure_phase": first_failure_phase,
        "failure_phase_label": PHASE_LABELS.get(first_failure_phase, ""),
        "phases": {
            "request": _phase(
                _phase_status(failed_ids["request"], request_ids),
                request_ids + failed_ids["request"],
            ),
            "request_processing": _phase(
                _phase_status(failed_ids["request_processing"], response_ids),
                failed_ids["request_processing"],
            ),
            "response": _phase(
                _response_status(
                    failed_ids["response"],
                    response_ids,
                    node.get("missing_response", False),
                ),
                response_ids + failed_ids["response"],
            ),
            "response_processing": _phase(
                _response_processing_status(
                    failed_ids["response_processing"],
                    failed_ids["unknown"],
                    response_ids,
                ),
                failed_ids["response_processing"] + failed_ids["unknown"],
            ),
        },
    }
