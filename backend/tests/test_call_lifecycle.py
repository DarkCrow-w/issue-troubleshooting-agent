from troubleshooter.analysis.lifecycle import analyze_call_lifecycle
from troubleshooter.domain.models import Event


def _event(event_id: str, timestamp: str, kind: str) -> Event:
    return Event(
        id=event_id,
        timestamp=timestamp,
        service="cm-gateway",
        kind=kind,
    )


def test_request_processing_error_does_not_mark_request_transport_as_failed():
    """请求已成功到达后，业务处理错误不能显示成“请求发送失败”。"""
    request = _event("request", "2026-09-22T10:00:00.000+08:00", "request")
    processing_error = _event("error", "2026-09-22T10:00:00.100+08:00", "log")
    response = _event("response", "2026-09-22T10:00:00.200+08:00", "response")
    events = {event.id: event for event in (request, processing_error, response)}
    node = {
        "request_ids": [request.id],
        "response_ids": [response.id],
        "evidence_ids": [request.id, processing_error.id, response.id],
    }
    failures = {
        processing_error.id: {
            "event_id": processing_error.id,
            "reasons": ["错误级别日志"],
        }
    }

    lifecycle = analyze_call_lifecycle(node, events, failures)

    assert lifecycle["phases"]["request"]["status"] == "success"
    assert lifecycle["phases"]["request_processing"]["status"] == "failed"
    assert lifecycle["failure_phase"] == "request_processing"
