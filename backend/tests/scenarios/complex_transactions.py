"""从真实日志截图的结构特征抽象出的 50 组全合成测试数据。

这里刻意不复制截图中的任何真实业务值。每个场景使用独立的 synthetic ID，
同时保留 Splunk result 包装、Kubernetes/Envoy 噪声、转义 JSON 等结构特征。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScenarioExpectation:
    """Agent 最终报告中必须满足的业务事实。"""

    observed_events: int | None = None
    services: set[str] | None = None
    node_count: int | None = None
    edge_count: int | None = None
    failure_service: str | None = None
    failure_reason: str | None = None
    no_failure: bool = False
    warning_contains: str | None = None
    exception_type: str | None = None
    unknown_contains: str | None = None
    forbidden_text: tuple[str, ...] = ()
    stored_contains_text: tuple[str, ...] = ()
    cleaning_reduced: bool | None = None


@dataclass(frozen=True)
class Scenario:
    """一笔独立交易及其可验证预期。"""

    number: int
    title: str
    category: str
    records: list[dict[str, Any]]
    expected: ScenarioExpectation
    cleaning_enabled: bool = True

    @property
    def id(self) -> str:
        return f"complex-{self.number:02d}"

    @property
    def correlation_id(self) -> str:
        return f"synthetic-transaction-{self.number:02d}"


def _time(second: int, millis: int = 0) -> str:
    return f"2026-07-28T16:51:{second:02d}.{millis:03d}+08:00"


def _record(
    case: int,
    ordinal: int,
    service: str = "cm-gateway",
    event_type: str = "request",
    **changes: Any,
) -> dict[str, Any]:
    """生成接近截图结构的日志，并加入常见但无分析价值的基础设施字段。"""

    correlation_id = f"synthetic-transaction-{case:02d}"
    record: dict[str, Any] = {
        "_time": _time(ordinal),
        "_cd": f"synthetic-bucket:{case * 100 + ordinal}",
        "index": "demo_transactions",
        "source": "/var/log/containers/synthetic.log",
        "sourcetype": "kube:container:java",
        "app": service,
        "pod": f"{service}-{case:02d}-abc",
        "container_name": service,
        "cluster_name": "synthetic-cluster",
        "namespace": "synthetic-payments",
        "eventType": event_type,
        "correlationId": correlation_id,
        "level": "INFO",
        "serviceId": f"/synthetic/{service}/operation",
        "IN_METHOD": "POST",
    }
    record.update(changes)
    return record


def _wrap(*records: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"preview": False, "result": record} for record in records]


def _success_chain(case: int, services: tuple[str, ...] = ("cm-gateway", "cm-acct-scene")):
    records: list[dict[str, Any]] = []
    parent = ""
    for index, service in enumerate(services):
        call_id = f"span-{case:02d}-{index}"
        common = {
            "callId": call_id,
            "parentCallId": parent,
            "direction": "outbound",
            "serviceId": f"/synthetic/{service}/execute",
        }
        records.append(
            _record(
                case,
                index * 2 + 1,
                service,
                "request",
                reqMessage=json.dumps(
                    {
                        "systemHeader": {"sequenceNumber": f"synthetic-transaction-{case:02d}"},
                        "amount": "88.00",
                    }
                ),
                **common,
            )
        )
        records.append(
            _record(
                case,
                index * 2 + 2,
                service,
                "response",
                response={"code": "0", "message": "accepted"},
                httpStatus=200,
                **common,
            )
        )
        parent = call_id
    return _wrap(*records)


def _single_failure(
    case: int,
    service: str = "cm-acct-scene",
    event_type: str = "response",
    **changes: Any,
) -> list[dict[str, Any]]:
    return _wrap(
        _record(
            case,
            1,
            service,
            event_type,
            callId=f"failure-{case:02d}",
            **changes,
        )
    )


def _scenario(
    number: int,
    title: str,
    category: str,
    records: list[dict[str, Any]],
    expected: ScenarioExpectation,
    cleaning_enabled: bool = True,
) -> Scenario:
    return Scenario(number, title, category, records, expected, cleaning_enabled)


def _build_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []

    # 01-10：截图中直接出现的 Splunk / Java 字段形态。
    scenarios.append(
        _scenario(
            1,
            "Splunk result 包装的两服务成功链路",
            "截图结构",
            _success_chain(1),
            ScenarioExpectation(
                observed_events=4,
                services={"cm-gateway", "cm-acct-scene"},
                node_count=2,
                edge_count=1,
                no_failure=True,
            ),
        )
    )
    mixed = _success_chain(2)
    mixed[0]["result"]["appName"] = mixed[0]["result"].pop("app")
    scenarios.append(
        _scenario(
            2,
            "appName 与 app 混合",
            "截图结构",
            mixed,
            ScenarioExpectation(
                observed_events=4,
                services={"cm-gateway", "cm-acct-scene"},
                node_count=2,
                edge_count=1,
                no_failure=True,
            ),
        )
    )
    nested = _record(
        3,
        1,
        callId="nested-3",
        reqMessage=json.dumps({"systemHeader": {"sequenceNumber": "synthetic-transaction-03"}}),
    )
    nested.pop("correlationId")
    scenarios.append(
        _scenario(
            3,
            "关联 ID 仅存在于 reqMessage.systemHeader",
            "截图结构",
            _wrap(nested),
            ScenarioExpectation(
                observed_events=1,
                services={"cm-gateway"},
                node_count=1,
                no_failure=True,
                unknown_contains="未找到可配对响应",
            ),
        )
    )
    double = _record(
        4,
        1,
        callId="double-4",
        reqMessage=json.dumps(
            json.dumps({"correlationId": "synthetic-transaction-04", "payload": {"value": 4}})
        ),
    )
    double.pop("correlationId")
    scenarios.append(
        _scenario(
            4,
            "双层转义 JSON 请求体",
            "截图结构",
            _wrap(double),
            ScenarioExpectation(
                observed_events=1, services={"cm-gateway"}, node_count=1, no_failure=True
            ),
        )
    )
    composite = _record(
        5,
        1,
        "comet-gateway-service",
        callId="composite-5",
        correlationId=None,
        seqNo="synthetic-transaction-05:SYN-BUSINESS-005",
    )
    scenarios.append(
        _scenario(
            5,
            "复合 seqNo 拆出根交易 ID",
            "截图结构",
            _wrap(composite),
            ScenarioExpectation(
                observed_events=1, services={"comet-gateway-service"}, node_count=1, no_failure=True
            ),
        )
    )
    raw_only = {"_raw": json.dumps(_record(6, 1, callId="raw-6"))}
    scenarios.append(
        _scenario(
            6,
            "字段只存在于 _raw JSON",
            "截图结构",
            _wrap(raw_only),
            ScenarioExpectation(
                observed_events=1, services={"cm-gateway"}, node_count=1, no_failure=True
            ),
        )
    )
    conflict = _record(
        7,
        1,
        "cm-gateway",
        callId="conflict-7",
        _raw=json.dumps(
            {
                "app": "wrong-service",
                "correlationId": "synthetic-transaction-07",
                "eventType": "request",
            }
        ),
    )
    scenarios.append(
        _scenario(
            7,
            "Splunk 提取字段与 _raw 冲突",
            "截图结构",
            _wrap(conflict),
            ScenarioExpectation(
                observed_events=1,
                services={"cm-gateway"},
                node_count=1,
                warning_contains="提取字段与 _raw 冲突",
            ),
        )
    )
    preview = [
        {"preview": True, "result": _record(8, 1, "preview-should-not-appear")},
        *_success_chain(8, ("cm-gateway",)),
    ]
    scenarios.append(
        _scenario(
            8,
            "忽略 Splunk preview 结果",
            "截图结构",
            preview,
            ScenarioExpectation(
                observed_events=2, services={"cm-gateway"}, node_count=1, no_failure=True
            ),
        )
    )
    service_data = _record(
        9,
        1,
        callId="service-data-9",
        correlationId=None,
        serviceData=json.dumps(
            {"correlationId": "synthetic-transaction-09", "systemHeader": {"channel": "MOBILE"}}
        ),
    )
    scenarios.append(
        _scenario(
            9,
            "serviceData 中提取关联 ID",
            "截图结构",
            _wrap(service_data),
            ScenarioExpectation(
                observed_events=1, services={"cm-gateway"}, node_count=1, no_failure=True
            ),
        )
    )
    cm_param = _record(
        10,
        1,
        callId="cm-param-10",
        correlationId=None,
        CM_PARAM=json.dumps({"seqNo": "synthetic-transaction-10", "IN_ADDRESS": "synthetic-host"}),
    )
    scenarios.append(
        _scenario(
            10,
            "CM_PARAM 中提取 seqNo",
            "截图结构",
            _wrap(cm_param),
            ScenarioExpectation(
                observed_events=1, services={"cm-gateway"}, node_count=1, no_failure=True
            ),
        )
    )

    # 11-20：失败信号判定。
    scenarios.append(
        _scenario(
            11,
            "HTTP 400 客户端错误",
            "失败定位",
            _single_failure(11, httpStatus=400, response={"code": "0"}),
            ScenarioExpectation(failure_service="cm-acct-scene", failure_reason="HTTP 400"),
        )
    )
    scenarios.append(
        _scenario(
            12,
            "HTTP 500 服务端错误",
            "失败定位",
            _single_failure(12, httpStatus=500, response={"code": "0"}),
            ScenarioExpectation(failure_service="cm-acct-scene", failure_reason="HTTP 500"),
        )
    )
    scenarios.append(
        _scenario(
            13,
            "带原因短语的 HTTP 状态",
            "失败定位",
            _single_failure(13, status="503 Service Unavailable", response={"code": "0"}),
            ScenarioExpectation(failure_service="cm-acct-scene", failure_reason="HTTP 503"),
        )
    )
    scenarios.append(
        _scenario(
            14,
            "响应体中的非成功业务码",
            "失败定位",
            _single_failure(14, httpStatus=200, response={"result": {"returnCode": "ACCT_404"}}),
            ScenarioExpectation(failure_service="cm-acct-scene", failure_reason="ACCT_404"),
        )
    )
    scenarios.append(
        _scenario(
            15,
            "顶层 errorCode",
            "失败定位",
            _single_failure(15, httpStatus=200, errorCode="LIMIT_EXCEEDED"),
            ScenarioExpectation(failure_service="cm-acct-scene", failure_reason="LIMIT_EXCEEDED"),
        )
    )
    scenarios.append(
        _scenario(
            16,
            "数字 0 成功业务码",
            "失败定位",
            _single_failure(16, httpStatus=200, response={"code": 0}),
            ScenarioExpectation(no_failure=True),
        )
    )
    scenarios.append(
        _scenario(
            17,
            "SUCCESS 成功业务码",
            "失败定位",
            _single_failure(17, httpStatus=200, response={"code": "SUCCESS"}),
            ScenarioExpectation(no_failure=True),
        )
    )
    scenarios.append(
        _scenario(
            18,
            "未知业务码判为失败",
            "失败定位",
            _single_failure(18, httpStatus=200, response={"code": "PENDING_REVIEW"}),
            ScenarioExpectation(failure_service="cm-acct-scene", failure_reason="PENDING_REVIEW"),
        )
    )
    scenarios.append(
        _scenario(
            19,
            "ERROR 级别日志",
            "失败定位",
            _single_failure(
                19, event_type="log", level="error", message="synthetic validation failed"
            ),
            ScenarioExpectation(failure_service="cm-acct-scene", failure_reason="错误级别日志"),
        )
    )
    scenarios.append(
        _scenario(
            20,
            "FATAL 级别日志",
            "失败定位",
            _single_failure(
                20, event_type="log", level="FATAL", message="synthetic process halted"
            ),
            ScenarioExpectation(failure_service="cm-acct-scene", failure_reason="错误级别日志"),
        )
    )

    # 21-25：Java 异常形态。
    stack = (
        "java.lang.IllegalStateException: synthetic state\n\tat demo.Service.run(Service.java:42)"
    )
    scenarios.append(
        _scenario(
            21,
            "stacktrace 字段中的 Java 异常",
            "Java异常",
            _single_failure(21, event_type="exception", stacktrace=stack),
            ScenarioExpectation(
                failure_service="cm-acct-scene",
                failure_reason="IllegalStateException",
                exception_type="java.lang.IllegalStateException",
            ),
        )
    )
    cause_stack = "java.lang.RuntimeException: wrapper\n\tat demo.Service.run(Service.java:20)\nCaused by: java.net.SocketTimeoutException: synthetic timeout\n\tat demo.Client.call(Client.java:10)"
    scenarios.append(
        _scenario(
            22,
            "Java caused by 异常链",
            "Java异常",
            _single_failure(22, event_type="exception", exception=cause_stack),
            ScenarioExpectation(
                failure_service="cm-acct-scene",
                failure_reason="RuntimeException",
                exception_type="java.lang.RuntimeException",
            ),
        )
    )
    scenarios.append(
        _scenario(
            23,
            "message 字段中的 Java 异常",
            "Java异常",
            _single_failure(
                23,
                event_type="log",
                message="request failed: java.lang.NullPointerException: synthetic null",
            ),
            ScenarioExpectation(
                failure_service="cm-acct-scene",
                failure_reason="NullPointerException",
                exception_type="java.lang.NullPointerException",
            ),
        )
    )
    scenarios.append(
        _scenario(
            24,
            "throwable 字段中的 Java 异常",
            "Java异常",
            _single_failure(
                24,
                event_type="log",
                throwable="org.springframework.dao.DataAccessException: synthetic db failure",
            ),
            ScenarioExpectation(
                failure_service="cm-acct-scene",
                failure_reason="DataAccessException",
                exception_type="org.springframework.dao.DataAccessException",
            ),
        )
    )
    raw_error = _record(
        25,
        1,
        "cm-acct-scene",
        "log",
        _raw="correlationId=synthetic-transaction-25 java.lang.OutOfMemoryError: synthetic heap",
        level="INFO",
    )
    scenarios.append(
        _scenario(
            25,
            "非 JSON _raw 中的 Java Error",
            "Java异常",
            _wrap(raw_error),
            ScenarioExpectation(
                failure_service="cm-acct-scene",
                failure_reason="OutOfMemoryError",
                exception_type="java.lang.OutOfMemoryError",
            ),
        )
    )

    # 26-35：请求响应配对、重试、并发与调用图。
    scenarios.append(
        _scenario(
            26,
            "同 callId 请求响应正确配对",
            "调用图",
            _success_chain(26, ("cm-gateway",)),
            ScenarioExpectation(observed_events=2, node_count=1, edge_count=0, no_failure=True),
        )
    )
    direction_pair = _success_chain(27, ("cm-gateway",))
    direction_pair[0]["result"]["direction"] = "outbound"
    direction_pair[1]["result"]["direction"] = "inbound"
    scenarios.append(
        _scenario(
            27,
            "请求与响应方向字段不同仍应配对",
            "调用图",
            direction_pair,
            ScenarioExpectation(observed_events=2, node_count=1, no_failure=True),
        )
    )
    scenarios.append(
        _scenario(
            28,
            "请求缺少响应",
            "调用图",
            _wrap(
                _record(
                    28,
                    1,
                    callId="missing-28",
                    reqMessage={"correlationId": "synthetic-transaction-28"},
                )
            ),
            ScenarioExpectation(
                observed_events=1,
                node_count=1,
                no_failure=True,
                unknown_contains="未找到可配对响应",
            ),
        )
    )
    duplicate_requests = _wrap(
        _record(29, 1, callId="ambiguous-29"),
        _record(29, 2, callId="ambiguous-29"),
        _record(29, 3, event_type="response", callId="ambiguous-29", response={"code": "0"}),
    )
    scenarios.append(
        _scenario(
            29,
            "重复请求标记配对歧义",
            "调用图",
            duplicate_requests,
            ScenarioExpectation(observed_events=3, node_count=1, no_failure=True),
        )
    )
    retry_records = _wrap(
        _record(30, 1, callId="retry-30", attempt="1"),
        _record(30, 2, event_type="response", callId="retry-30", attempt="1", httpStatus=503),
        _record(30, 3, callId="retry-30", attempt="2"),
        _record(
            30,
            4,
            event_type="response",
            callId="retry-30",
            attempt="2",
            httpStatus=200,
            response={"code": "0"},
        ),
    )
    scenarios.append(
        _scenario(
            30,
            "Envoy 两次重试分别配对",
            "调用图",
            retry_records,
            ScenarioExpectation(
                observed_events=4,
                node_count=2,
                failure_service="cm-gateway",
                failure_reason="HTTP 503",
            ),
        )
    )
    instance_records = _wrap(
        _record(31, 1, callId="shared-31", pod="gateway-a"),
        _record(
            31,
            2,
            event_type="response",
            callId="shared-31",
            pod="gateway-a",
            response={"code": "0"},
        ),
        _record(31, 3, callId="shared-31", pod="gateway-b"),
        _record(
            31,
            4,
            event_type="response",
            callId="shared-31",
            pod="gateway-b",
            response={"code": "0"},
        ),
    )
    scenarios.append(
        _scenario(
            31,
            "不同实例复用 callId 不串单",
            "调用图",
            instance_records,
            ScenarioExpectation(observed_events=4, node_count=2, no_failure=True),
        )
    )
    scenarios.append(
        _scenario(
            32,
            "三服务显式 parentCallId 链路",
            "调用图",
            _success_chain(32, ("cm-gateway", "cm-acct-scene", "ledger-service")),
            ScenarioExpectation(observed_events=6, node_count=3, edge_count=2, no_failure=True),
        )
    )
    inferred = _wrap(
        _record(33, 1, "cm-gateway", callId="infer-parent-33", peerService="cm-acct-scene"),
        _record(33, 2, "cm-acct-scene", callId="infer-child-33"),
    )
    scenarios.append(
        _scenario(
            33,
            "peerService 唯一候选推断链路",
            "调用图",
            inferred,
            ScenarioExpectation(observed_events=2, node_count=2, edge_count=1, no_failure=True),
        )
    )
    ambiguous_peer = _wrap(
        _record(34, 1, "cm-gateway", callId="infer-source-34", peerService="cm-acct-scene"),
        _record(34, 2, "cm-acct-scene", callId="candidate-a-34"),
        _record(34, 3, "cm-acct-scene", callId="candidate-b-34"),
    )
    scenarios.append(
        _scenario(
            34,
            "peerService 多候选不猜测链路",
            "调用图",
            ambiguous_peer,
            ScenarioExpectation(
                observed_events=3,
                node_count=3,
                edge_count=0,
                no_failure=True,
                unknown_contains="缺少足够证据",
            ),
        )
    )
    exception_only = _record(
        35,
        1,
        "ledger-service",
        "exception",
        serviceId="/ledger/book",
        stacktrace="java.lang.IllegalArgumentException: synthetic amount",
    )
    scenarios.append(
        _scenario(
            35,
            "仅有异常日志也保留服务节点",
            "调用图",
            _wrap(exception_only),
            ScenarioExpectation(
                observed_events=1,
                node_count=1,
                failure_service="ledger-service",
                failure_reason="IllegalArgumentException",
            ),
        )
    )

    # 36-43：时间、归属与标识符边界。
    out_of_order = _wrap(
        _record(36, 9, "downstream", "response", callId="late-36", httpStatus=500),
        _record(36, 2, "upstream", "response", callId="early-36", httpStatus=400),
    )
    scenarios.append(
        _scenario(
            36,
            "输入乱序仍按时间定位最早失败",
            "边界数据",
            out_of_order,
            ScenarioExpectation(
                observed_events=2, failure_service="upstream", failure_reason="HTTP 400"
            ),
        )
    )
    epoch = _record(37, 1, callId="epoch-37", _time=1785228661.0)
    scenarios.append(
        _scenario(
            37,
            "Unix epoch 时间戳",
            "边界数据",
            _wrap(epoch),
            ScenarioExpectation(observed_events=1, node_count=1, no_failure=True),
        )
    )
    malformed_time = _record(38, 1, callId="bad-time-38", _time="not-a-time")
    scenarios.append(
        _scenario(
            38,
            "非法时间日志被范围查询排除",
            "边界数据",
            _wrap(malformed_time),
            ScenarioExpectation(
                observed_events=0, services=set(), warning_contains="没有可确认归属"
            ),
        )
    )
    missing_time = _record(39, 1, callId="missing-time-39")
    missing_time.pop("_time")
    scenarios.append(
        _scenario(
            39,
            "缺失时间日志被范围查询排除",
            "边界数据",
            _wrap(missing_time),
            ScenarioExpectation(
                observed_events=0, services=set(), warning_contains="没有可确认归属"
            ),
        )
    )
    outside = _record(
        40, 1, "outside-service", callId="outside-40", _time="2026-07-28T18:00:00+08:00"
    )
    inside = _record(40, 2, "inside-service", callId="inside-40")
    scenarios.append(
        _scenario(
            40,
            "严格限制查询时间窗",
            "边界数据",
            _wrap(outside, inside),
            ScenarioExpectation(
                observed_events=1, services={"inside-service"}, node_count=1, no_failure=True
            ),
        )
    )
    unrelated = _record(
        41,
        1,
        "unrelated-service",
        callId="unrelated-41",
        correlationId="another-synthetic-transaction",
    )
    related = _record(41, 2, "cm-gateway", callId="related-41")
    scenarios.append(
        _scenario(
            41,
            "排除其他交易的日志",
            "边界数据",
            _wrap(unrelated, related),
            ScenarioExpectation(
                observed_events=1,
                services={"cm-gateway"},
                forbidden_text=("another-synthetic-transaction", "unrelated-service"),
                no_failure=True,
            ),
        )
    )
    hsbc_id = _record(
        42,
        1,
        callId="header-42",
        correlationId=None,
        x_hsbc_request_correlation_id="synthetic-transaction-42",
    )
    scenarios.append(
        _scenario(
            42,
            "请求头关联 ID",
            "边界数据",
            _wrap(hsbc_id),
            ScenarioExpectation(
                observed_events=1, services={"cm-gateway"}, node_count=1, no_failure=True
            ),
        )
    )
    request_id = _record(
        43, 1, callId="request-id-43", correlationId=None, x_request_id="synthetic-transaction-43"
    )
    scenarios.append(
        _scenario(
            43,
            "x_request_id 作为检索入口",
            "边界数据",
            _wrap(request_id),
            ScenarioExpectation(
                observed_events=1, services={"cm-gateway"}, node_count=1, no_failure=True
            ),
        )
    )

    # 44-50：原始数据保留、清洗、重复数据与综合失败。
    secret_dict = _record(
        44,
        1,
        callId="secret-44",
        reqMessage={
            "correlationId": "synthetic-transaction-44",
            "x_hsbc_client_secret": "SYNTHETIC_SECRET_44",
            "authorization": "Bearer SYNTHETIC_TOKEN_44",
            "accountNumber": "SYNTHETIC_ACCOUNT_44",
        },
    )
    scenarios.append(
        _scenario(
            44,
            "结构化敏感字段原样保留",
            "数据保留与清洗",
            _wrap(secret_dict),
            ScenarioExpectation(
                observed_events=1,
                node_count=1,
                no_failure=True,
                stored_contains_text=(
                    "SYNTHETIC_SECRET_44",
                    "SYNTHETIC_TOKEN_44",
                    "SYNTHETIC_ACCOUNT_44",
                ),
            ),
        )
    )
    secret_text = _record(
        45,
        1,
        callId="secret-45",
        message='headers={x_hsbc_e2e_trust_token="SYNTHETIC_TOKEN_45", api-key="sk-synthetic000000045"}',
    )
    scenarios.append(
        _scenario(
            45,
            "字符串 token 与 API key 原样保留",
            "数据保留与清洗",
            _wrap(secret_text),
            ScenarioExpectation(
                observed_events=1,
                node_count=1,
                no_failure=True,
                stored_contains_text=("SYNTHETIC_TOKEN_45", "sk-synthetic000000045"),
            ),
        )
    )
    large_payload = (
        "x" * 1_500_000
        + " java.sql.SQLTimeoutException: synthetic slow query "
        + "y" * 1_500_000
        + ' "returnCode":"SYNTHETIC_REJECTED" '
        + "z" * 1_500_000
    )
    large_body = {
        "correlationId": "synthetic-transaction-46",
        "seqNo": "synthetic-transaction-46",
        "unusedPayload": large_payload,
        "systemHeader": {"sequenceNumber": "synthetic-transaction-46"},
    }
    scenarios.append(
        _scenario(
            46,
            "清洗 4.5MB 请求体并保留关键字段和错误窗口",
            "数据保留与清洗",
            _wrap(_record(46, 1, callId="large-46", reqMessage=large_body)),
            ScenarioExpectation(
                observed_events=1,
                node_count=1,
                no_failure=True,
                cleaning_reduced=True,
            ),
        )
    )
    raw_large = {"correlationId": "synthetic-transaction-47", "payload": "y" * 5000}
    scenarios.append(
        _scenario(
            47,
            "关闭清洗仍保持失败判定",
            "数据保留与清洗",
            _single_failure(47, httpStatus=502, response=raw_large),
            ScenarioExpectation(
                observed_events=1, failure_service="cm-acct-scene", failure_reason="HTTP 502"
            ),
            cleaning_enabled=False,
        )
    )
    duplicate = _record(48, 1, callId="duplicate-48")
    duplicate.pop("_cd")
    scenarios.append(
        _scenario(
            48,
            "无 Splunk 唯一位置的相同日志保留两次",
            "数据保留与清洗",
            _wrap(duplicate, dict(duplicate)),
            ScenarioExpectation(observed_events=2, node_count=1, no_failure=True),
        )
    )
    failures = _wrap(
        _record(49, 8, "cm-gateway", "response", callId="late-49", httpStatus=502),
        _record(
            49,
            3,
            "cm-acct-scene",
            "response",
            callId="early-49",
            response={"code": "ACCT_LOCKED"},
            httpStatus=200,
        ),
        _record(
            49,
            5,
            "ledger-service",
            "exception",
            stacktrace="java.sql.SQLException: synthetic deadlock",
        ),
    )
    scenarios.append(
        _scenario(
            49,
            "多类失败信号选择最早观测点",
            "综合",
            failures,
            ScenarioExpectation(
                observed_events=3, failure_service="cm-acct-scene", failure_reason="ACCT_LOCKED"
            ),
        )
    )
    mixed_final = _wrap(
        _record(
            50, 1, "cm-gateway", "response", callId="ok-50", httpStatus=200, response={"code": "0"}
        ),
        _record(
            50,
            2,
            "cm-acct-scene",
            "exception",
            callId="exception-50",
            stacktrace="java.util.concurrent.TimeoutException: synthetic deadline",
        ),
    )
    scenarios.append(
        _scenario(
            50,
            "上游成功但下游随后抛出异常",
            "综合",
            mixed_final,
            ScenarioExpectation(
                observed_events=2,
                failure_service="cm-acct-scene",
                failure_reason="TimeoutException",
                exception_type="java.util.concurrent.TimeoutException",
            ),
        )
    )

    return scenarios


SCENARIOS = _build_scenarios()
