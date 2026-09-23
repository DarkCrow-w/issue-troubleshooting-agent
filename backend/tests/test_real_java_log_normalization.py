"""基于真实 Splunk/Java 结构重写的安全回归样本。"""

from troubleshooter.analysis.failures import failure_localization
from troubleshooter.analysis.journey import transaction_journey
from troubleshooter.analysis.ordering import time_key
from troubleshooter.analysis.requests import request_response
from troubleshooter.analysis.trace import trace_reconstruction
from troubleshooter.logs.normalization import normalize

CORRELATION_ID = "4f0ab148-4dca-4b73-9a87-7398bcbe3df1"

CONFIG = {
    "correlation_fields": [
        "correlationId",
        "seqNo",
        "x_hsbc_request_correlation_id",
    ],
    "composite_id_services": ["cm-gateway", "comet-gateway-service"],
    "service_aliases": {},
}
FLOW_CONFIG = {
    **CONFIG,
    "success_business_codes": ["0", "0000", "SUCCESS"],
    "topology": {
        "service_roles": {},
        "cm_service_patterns": ["^cm-", "^comet-"],
        "upstream_service_patterns": [],
        "downstream_service_patterns": [],
        "downstream_api_patterns": [],
        "upstream_input_error_patterns": [],
    },
}


def java_record(
    timestamp: str,
    service: str,
    level: str,
    logger: str,
    message: str,
    **fields,
) -> dict:
    context = (
        f"tenant=channel pod={service}-pod-1 appName={service} "
        f"seqNo={CORRELATION_ID} correlationId={CORRELATION_ID}"
    )
    raw = (
        f"#[{timestamp.replace('T', ' ')[:-6].replace('.', ',')}] [{context}] "
        f"[scene-demo] [worker-1] {level} {logger} - message={message}"
    )
    return {
        "_time": timestamp,
        "_raw": raw,
        "appName": service,
        "pod": f"{service}-pod-1",
        "seqNo": CORRELATION_ID,
        "correlationId": CORRELATION_ID,
        **fields,
    }


def test_send_request_extracts_transport_and_trace_fields():
    message = (
        "send req message url is[ http://cm-scene-service/cust/scene/1400/10611013 ] "
        "x-b3-spanid=gw-scene-01 x-b3-parentspanid=gateway-in-01 "
        'body is[ {"sysHead":{"seqNo":"' + CORRELATION_ID + '"}} ]'
    )

    event = normalize(
        java_record(
            "2026-09-21T14:10:47.135+08:00",
            "cm-gateway",
            "INFO",
            "example.OKHttpLogInterceptor.intercept:36",
            message,
        ),
        CONFIG,
    )

    assert event.kind == "request"
    assert event.direction == "outbound"
    assert event.api == "/cust/scene/1400/10611013"
    assert event.peer_service == "cm-scene-service"
    assert event.call_id == "gw-scene-01"
    assert event.parent_call_id == "gateway-in-01"
    assert event.level == "INFO"
    assert event.request["sysHead"]["seqNo"] == CORRELATION_ID


def test_receive_response_extracts_http_status_from_message():
    event = normalize(
        java_record(
            "2026-09-21T14:10:47.292+08:00",
            "cm-gateway",
            "INFO",
            "example.OKHttpLogInterceptor.intercept:48",
            "receive res message timeUse[ 156 ms] status code[ 200 ], "
            "url is [ http://cm-scene-service/cust/scene/1400/10611013 ] "
            "x-b3-spanid=gw-scene-01",
        ),
        CONFIG,
    )

    assert event.kind == "response"
    assert event.direction == "inbound"
    assert event.http_status == 200
    assert event.call_id == "gw-scene-01"
    assert event.api == "/cust/scene/1400/10611013"


def test_flow_request_is_treated_as_inbound():
    event = normalize(
        java_record(
            "2026-09-21T14:10:47.137+08:00",
            "cm-cust-scene",
            "INFO",
            "example.DefaultFlowChain.invokeFlow:150",
            f'Executor flow[sceneDemoFlow] request is[ {{"correlationId":"{CORRELATION_ID}"}} ] '
            "x-b3-spanid=scene-in x-b3-parentspanid=gw-scene",
        ),
        CONFIG,
    )

    assert event.kind == "request"
    assert event.direction == "inbound"


def test_exception_uses_full_raw_when_splunk_message_is_shortened():
    record = java_record(
        "2026-09-21T14:10:47.261+08:00",
        "cm-cust-scene",
        "DEBUG",
        "example.DecoratorRestApiClient.handleException:58",
        "handleException method:POST api:https://cards.internal.example/"
        "api/customers/card-info, exception= "
        "com.example.rest.RestResponseException: response error\n"
        "\tat com.example.rest.CommonRestApiClient.request(CommonRestApiClient.java:282)",
    )
    record["message"] = (
        "handleException method:POST "
        "api:https://cards.internal.example/api/customers/card-info"
    )

    event = normalize(record, CONFIG)

    assert event.kind == "exception"
    assert event.exception["type"] == "com.example.rest.RestResponseException"
    assert event.level == "DEBUG"
    assert event.method == "POST"
    assert event.api == "/api/customers/card-info"
    assert event.peer_service == "cards"


def test_bracketed_gateway_correlation_is_extracted():
    record = java_record(
        "2026-09-21T14:10:47.126+08:00",
        "comet-gateway-service",
        "INFO",
        "example.GlobalTraceFilter.doFilter:143",
        f"correlationId:[{CORRELATION_ID}]",
    )
    record.pop("seqNo")
    record.pop("correlationId")
    record["_raw"] = record["_raw"].replace(
        f"seqNo={CORRELATION_ID} correlationId={CORRELATION_ID}",
        "seqNo= correlationId=",
    )

    event = normalize(record, CONFIG)

    assert event.correlation_ids == [CORRELATION_ID]


def test_normalized_events_sort_by_millisecond_timestamp():
    later = normalize(
        java_record(
            "2026-09-21T14:10:47.292+08:00",
            "cm-gateway",
            "INFO",
            "example.Logger.method:1",
            "later",
        ),
        CONFIG,
    )
    earlier = normalize(
        java_record(
            "2026-09-21T14:10:47.126+08:00",
            "comet-gateway-service",
            "INFO",
            "example.Logger.method:1",
            "earlier",
        ),
        CONFIG,
    )

    assert sorted([later, earlier], key=time_key) == [earlier, later]


def test_trace_header_name_does_not_turn_cleanup_log_into_request():
    event = normalize(
        java_record(
            "2026-09-21T14:10:47.300+08:00",
            "cm-cust-scene",
            "DEBUG",
            "example.CometContext.clear:140",
            "Do context cleanup is end. "
            f"x-hsbc-request-correlation-id={CORRELATION_ID} x-request-id=req-01",
        ),
        CONFIG,
    )

    assert event.kind == "log"


def test_real_format_builds_call_tree_and_attributes_downstream_failure():
    gateway_request = java_record(
        "2026-09-21T14:10:47.135+08:00",
        "cm-gateway",
        "INFO",
        "example.OKHttpLogInterceptor.intercept:36",
        "send req message url is[ http://cm-scene-service/cust/scene/demo ] "
        "x-b3-spanid=gw-scene",
    )
    scene_request = java_record(
        "2026-09-21T14:10:47.137+08:00",
        "cm-cust-scene",
        "INFO",
        "example.DefaultFlowChain.invokeFlow:150",
        "Executor flow[sceneDemoFlow] request is[ {} ] "
        "x-b3-spanid=scene-in x-b3-parentspanid=gw-scene",
    )
    card_request = java_record(
        "2026-09-21T14:10:47.150+08:00",
        "cm-cust-scene",
        "INFO",
        "example.OKHttpLogInterceptor.intercept:36",
        "send req message url is[ https://cards.internal.example/api/card-info ] "
        "x-b3-spanid=card-call x-b3-parentspanid=scene-in",
    )
    card_response = java_record(
        "2026-09-21T14:10:47.250+08:00",
        "cm-cust-scene",
        "WARN",
        "example.OKHttpLogInterceptor.intercept:48",
        'receive res message status code[ 503 ] body is[ {"code":"CARD_UNAVAILABLE"} ] '
        "url is[ https://cards.internal.example/api/card-info ] x-b3-spanid=card-call",
    )
    events = [
        normalize(record, FLOW_CONFIG)
        for record in (gateway_request, scene_request, card_request, card_response)
    ]

    artifacts = {}
    artifacts["request-response"] = request_response(events, FLOW_CONFIG, artifacts)
    artifacts["trace-reconstruction"] = trace_reconstruction(
        events, FLOW_CONFIG, artifacts
    )
    artifacts["failure-localization"] = failure_localization(
        events, FLOW_CONFIG, artifacts
    )
    journey = transaction_journey(events, FLOW_CONFIG, artifacts)

    assert len(artifacts["trace-reconstruction"]["nodes"]) == 3
    assert len(artifacts["trace-reconstruction"]["edges"]) == 2
    assert journey["attribution"]["domain"] == "downstream"
    assert journey["attribution"]["phase"] == "response"
    assert journey["attribution"]["conclusion"]["owner"] == "下游 Support"
