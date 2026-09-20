import json

from troubleshooter.analysis import HANDLERS
from troubleshooter.logs.cleaning import clean_event, model_evidence
from troubleshooter.logs.normalization import normalize


def record(**changes):
    return {
        "_time": "2026-07-28T16:51:47.800+08:00",
        "appName": "cm-gateway",
        "correlationId": "opaque-not-a-uuid",
        "pod": "pod-1",
        **changes,
    }


def facts(events, config):
    output = {}
    for name, handler in HANDLERS.items():
        output[name.replace("_", "-")] = handler(events, config, output)
    return output


def test_compound_ids_and_embedded_json(config):
    event = normalize(
        record(
            seqNo="opaque-not-a-uuid:business-1",
            reqMessage='{"systemHeader":{"sequenceNumber":"business-1"}}',
        ),
        config,
    )
    assert event.ids["seqNo"] == "opaque-not-a-uuid:business-1"
    assert event.ids["businessSequence"] == "business-1"
    assert "opaque-not-a-uuid" in event.correlation_ids
    assert event.request["systemHeader"]["sequenceNumber"] == "business-1"


def test_raw_only_and_conflicting_fields(config):
    event = normalize(record(_raw=json.dumps({"correlationId": "other", "path": "/api"})), config)
    assert event.correlation_ids == ["opaque-not-a-uuid"]
    assert event.api == "/api"
    assert any("冲突" in warning for warning in event.parse_warnings)


def test_java_exception_and_malformed_payload(config):
    event = normalize(
        record(
            CM_PARAM='{sceneReqMessage={"test":1}}',
            _raw="com.example.WrappedException: wrapper\n\tat a.b(C.java:1)\n"
            "Caused by: java.sql.SQLTimeoutException: slow query",
        ),
        config,
    )
    assert event.exception["causes"][0]["type"] == "java.sql.SQLTimeoutException"
    assert event.parse_warnings
    assert event.request.startswith("{sceneReqMessage")


def test_time_adjacency_does_not_create_edges(config):
    events = [
        normalize(record(appName=service, eventType="request", path="/a"), config)
        for service in ("first", "second")
    ]
    graph = facts(events, config)["trace-reconstruction"]
    assert graph["edges"] == []
    assert len(graph["nodes"]) == 2


def test_explicit_edges_and_retries(config):
    rows = [
        record(eventType="request", callId="parent", path="/a"),
        record(
            appName="downstream",
            eventType="request",
            callId="child",
            parentCallId="parent",
            attempt="1",
        ),
        record(
            appName="downstream",
            eventType="request",
            callId="child",
            parentCallId="parent",
            attempt="2",
        ),
    ]
    graph = facts([normalize(row, config) for row in rows], config)["trace-reconstruction"]
    assert len(graph["nodes"]) == 3
    assert len(graph["edges"]) == 2
    assert all(edge["certainty"] == "confirmed" for edge in graph["edges"])


def test_business_failure_even_http_200(config):
    event = normalize(record(httpStatus=200, response={"code": "REJECTED"}), config)
    failures = facts([event], config)["failure-localization"]["failures"]
    assert len(failures) == 1
    assert "REJECTED" in failures[0]["reasons"][0]


def test_unknown_responses_not_paired_by_time(config):
    events = [
        normalize(record(eventType="request"), config),
        normalize(record(eventType="response", _time="2026-07-28T16:51:48+08:00"), config),
    ]
    calls = facts(events, config)["request-response"]["calls"]
    assert len(calls) == 2 and calls[0]["missing_response"]


def test_cleaning_preserves_identity_and_causes(config):
    rows = [
        record(
            eventType="request",
            callId=str(i),
            reqMessage={"data": "x" * 50000},
            _time=f"2026-07-28T16:51:4{i}+08:00",
        )
        for i in (1, 2)
    ]
    events = [normalize(row, config) for row in rows]
    evidence = {e.id: row for e, row in zip(events, rows)}
    cleaned = model_evidence(events, evidence, True, config["cleaning"])
    original = model_evidence(events, evidence, False, config["cleaning"])
    assert len(cleaned) == len(original) == 2
    assert cleaned[0]["id"] != cleaned[1]["id"]
    assert cleaned[0]["request"]["truncated"]
    assert len(json.dumps(cleaned)) < len(json.dumps(original))
    event = normalize(
        record(
            _raw="java.lang.IllegalStateException: failed\nCaused by: java.io.IOException: disk"
        ),
        config,
    )
    assert (
        clean_event(event, config["cleaning"])["exception"]["causes"] == event.exception["causes"]
    )


def test_large_log_keeps_head_tail_and_distributed_error_signals(config):
    middle_error = "java.sql.SQLTimeoutException: synthetic slow query"
    late_error = '"returnCode":"ACCT_REJECTED"'
    body = (
        "HEAD-MARKER"
        + "a" * 1_500_000
        + middle_error
        + "b" * 1_500_000
        + late_error
        + "c" * 1_500_000
        + "TAIL-MARKER"
    )
    event = normalize(record(eventType="request", reqMessage=body), config)
    cleaned = clean_event(event, config["cleaning"])["request"]
    retained = "".join(item["text"] for item in cleaned["excerpts"])

    assert cleaned["original_chars"] > 4_000_000
    assert cleaned["retained_chars"] <= config["cleaning"]["body_max_chars"]
    assert "HEAD-MARKER" in retained
    assert "TAIL-MARKER" in retained
    assert middle_error in retained
    assert "returnCode" in retained
    assert "ACCT_REJECTED" in retained


def test_large_stack_keeps_caused_by_near_the_end(config):
    lines = ["java.lang.RuntimeException: wrapper"]
    lines += [f"\tat demo.Service.call(Service.java:{line})" for line in range(150)]
    lines += [
        "Caused by: java.net.SocketTimeoutException: synthetic downstream timeout",
        "\tat demo.Client.call(Client.java:200)",
    ]
    event = normalize(record(stacktrace="\n".join(lines)), config)
    cleaned = clean_event(event, config["cleaning"])["exception"]

    assert cleaned["stack_truncated"] is True
    assert len(cleaned["stack"].splitlines()) <= config["cleaning"]["stack_max_frames"] + 3
    assert "Caused by: java.net.SocketTimeoutException" in cleaned["stack"]


def test_large_raw_finds_tail_exception_without_unbounded_regex(config):
    raw = "a" * 3_000_000 + " java.net.SocketTimeoutException: synthetic timeout"
    event = normalize(record(_raw=raw), config)

    assert event.exception["type"] == "java.net.SocketTimeoutException"


def test_single_line_multi_megabyte_exception_is_compacted(config):
    message = (
        "a" * 1_000_000
        + " Caused by: java.net.SocketTimeoutException: downstream read timed out "
        + "b" * 1_000_000
        + ' "returnCode":"DOCUMENT_TIMEOUT" '
        + "c" * 1_000_000
    )
    event = normalize(record(message=message), config)
    cleaned = clean_event(event, config["cleaning"])

    stack = cleaned["exception"]["stack"]
    assert cleaned["exception"]["stack_truncated"] is True
    assert len(stack) < 20_000
    assert "SocketTimeoutException" in stack
    assert "DOCUMENT_TIMEOUT" in stack
    assert len(cleaned["exception"]["message"]) < 5_000
    assert cleaned["message"] == {"same_content_as": "exception.stack"}


def test_deduplication_references_the_correct_payload_field(config):
    rows = [
        record(eventType="request", request={"same": "body"}),
        record(eventType="response", response={"same": "body"}),
    ]
    events = [normalize(row, config) for row in rows]
    cleaned = model_evidence(
        events, dict(zip([e.id for e in events], rows)), True, config["cleaning"]
    )
    assert cleaned[0]["request"] == {"same": "body"}
    assert cleaned[1]["response"] == {"same": "body"}


def test_clock_skew_does_not_reverse_explicit_relationship(config):
    parent = normalize(
        record(callId="p", eventType="request", _time="2026-07-28T16:52:00+08:00"), config
    )
    child = normalize(
        record(
            appName="child",
            callId="c",
            parentCallId="p",
            eventType="request",
            _time="2026-07-28T16:51:00+08:00",
        ),
        config,
    )
    graph = facts([parent, child], config)["trace-reconstruction"]
    assert graph["edges"][0]["source"] == parent.id
    assert graph["edges"][0]["target"] == child.id
    assert graph["timeline"][0]["event_id"] == child.id


def test_ambiguous_reused_call_id_cannot_prove_parent_instance(config):
    rows = [
        record(callId="p", eventType="request", _time=f"2026-07-28T16:51:0{i}+08:00")
        for i in (1, 2)
    ]
    rows.append(record(appName="child", callId="c", parentCallId="p", eventType="request"))
    graph = facts([normalize(row, config) for row in rows], config)["trace-reconstruction"]
    assert graph["nodes"][0]["pairing_ambiguous"]
    assert graph["edges"] == []


def test_event_id_ignores_query_specific_metadata(config):
    first = normalize(record(_cd="bucket:10", _raw="original event", _serial="1"), config)
    second = normalize(
        record(_cd="bucket:10", _raw="original event", _serial="5", extracted="extra"), config
    )
    assert first.id == second.id
    assert normalize(record(_serial="1"), config).id == normalize(record(_serial="2"), config).id
