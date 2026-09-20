#!/usr/bin/env python3
"""生成可直接交给 ReplaySource 的多交易演示日志。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "examples/demo-pack.json"


def event(
    transaction_id: str,
    second: int,
    millis: int,
    service: str,
    event_type: str,
    **fields: Any,
) -> dict[str, Any]:
    """构造带 Splunk 与 Kubernetes 常见字段的合成日志。"""

    record = {
        "index": "demo_transactions",
        "source": f"/var/log/containers/{service}.log",
        "sourcetype": "kube:container:java",
        "cluster_name": "demo-cluster",
        "namespace": "payments-demo",
        "pod": f"{service}-demo-01",
        "appName": service,
        "correlationId": transaction_id,
        "_time": f"2026-07-28T16:52:{second:02d}.{millis:03d}+08:00",
        "eventType": event_type,
        "level": "INFO",
    }
    record.update(fields)
    return {"preview": False, "result": record}


def call_pair(
    transaction_id: str,
    second: int,
    service: str,
    call_id: str,
    parent_call_id: str = "",
    path: str = "/demo/execute",
    response: dict[str, Any] | None = None,
    http_status: int = 200,
    attempt: str = "",
    response_second: int | None = None,
    response_millis: int = 800,
) -> list[dict[str, Any]]:
    common = {
        "callId": call_id,
        "parentCallId": parent_call_id,
        "serviceId": path,
        "direction": "outbound",
        "x_envoy_attempt_count": attempt,
    }
    request = event(
        transaction_id,
        second,
        100,
        service,
        "request",
        reqMessage={
            "systemHeader": {"sequenceNumber": transaction_id},
            "operation": "demo",
        },
        **common,
    )
    reply = event(
        transaction_id,
        response_second if response_second is not None else second,
        response_millis,
        service,
        "response",
        response=response or {"code": "0", "message": "success"},
        httpStatus=http_status,
        **common,
    )
    return [request, reply]


def success_demo() -> list[dict[str, Any]]:
    transaction = "demo-success-001"
    return [
        *call_pair(
            transaction,
            1,
            "cm-gateway",
            "success-gateway",
            path="/payments",
            response_second=4,
        ),
        *call_pair(
            transaction,
            2,
            "payment-service",
            "success-payment",
            "success-gateway",
            "/payments/authorize",
            response_second=4,
            response_millis=500,
        ),
        *call_pair(
            transaction,
            3,
            "ledger-service",
            "success-ledger",
            "success-payment",
            "/ledger/book",
        ),
    ]


def business_error_demo() -> list[dict[str, Any]]:
    transaction = "demo-business-error-001"
    return [
        *call_pair(
            transaction,
            5,
            "cm-gateway",
            "business-gateway",
            path="/transfers",
            response_second=7,
        ),
        *call_pair(
            transaction,
            6,
            "cm-acct-scene",
            "business-account",
            "business-gateway",
            "/accounts/reserve",
            response={
                "code": "LIMIT_EXCEEDED",
                "message": "daily transfer limit exceeded",
            },
        ),
    ]


def java_timeout_demo() -> list[dict[str, Any]]:
    transaction = "demo-java-timeout-001"
    records = call_pair(
        transaction,
        10,
        "cm-gateway",
        "timeout-gateway",
        path="/payments",
        response={"code": "UPSTREAM_TIMEOUT", "message": "payment service unavailable"},
        http_status=502,
        response_second=12,
    )
    records.append(
        event(
            transaction,
            11,
            200,
            "payment-service",
            "exception",
            serviceId="/payments/authorize",
            callId="timeout-payment",
            parentCallId="timeout-gateway",
            level="ERROR",
            stacktrace=(
                "com.demo.PaymentException: authorization failed\n"
                "\tat com.demo.PaymentService.authorize(PaymentService.java:88)\n"
                "Caused by: java.sql.SQLTimeoutException: connection pool exhausted\n"
                "\tat com.demo.PaymentRepository.lock(PaymentRepository.java:51)"
            ),
        )
    )
    return records


def retry_demo() -> list[dict[str, Any]]:
    transaction = "demo-retry-001"
    return [
        *call_pair(
            transaction,
            15,
            "cm-gateway",
            "retry-client",
            path="/customer/profile",
            response={"code": "TEMPORARY_UNAVAILABLE"},
            http_status=503,
            attempt="1",
        ),
        *call_pair(
            transaction,
            16,
            "cm-gateway",
            "retry-client",
            path="/customer/profile",
            response={"code": "0", "message": "retry succeeded"},
            attempt="2",
        ),
    ]


def multi_service_demo() -> list[dict[str, Any]]:
    transaction = "demo-multi-service-001"
    return [
        *call_pair(
            transaction,
            20,
            "cm-gateway",
            "multi-gateway",
            path="/transfers",
            response_second=25,
        ),
        *call_pair(
            transaction,
            21,
            "transfer-service",
            "multi-transfer",
            "multi-gateway",
            "/transfers/create",
            response_second=25,
            response_millis=500,
        ),
        *call_pair(
            transaction,
            22,
            "risk-service",
            "multi-risk",
            "multi-transfer",
            "/risk/check",
            response={
                "returnCode": "RISK_REJECTED",
                "message": "velocity rule matched",
            },
        ),
        *call_pair(
            transaction,
            23,
            "audit-service",
            "multi-audit",
            "multi-risk",
            "/audit/events",
        ),
    ]


def large_log_demo() -> list[dict[str, Any]]:
    transaction = "demo-large-log-001"
    # 错误放在数 MB 文本靠后位置，验证动态错误窗口，而不是只截取日志开头。
    large_message = (
        "START large synthetic log "
        + "a" * 1_000_000
        + " warning: dependency latency increased "
        + "b" * 1_000_000
        + " Caused by: java.net.SocketTimeoutException: downstream read timed out "
        + "c" * 1_000_000
        + ' "returnCode":"DOCUMENT_TIMEOUT" END'
    )
    return [
        event(
            transaction,
            30,
            100,
            "cm-gateway",
            "request",
            serviceId="/documents/archive",
            callId="large-gateway",
            reqMessage={
                "correlationId": transaction,
                "documentId": "SYNTHETIC-DOC-001",
            },
        ),
        event(
            transaction,
            31,
            500,
            "document-service",
            "log",
            serviceId="/documents/archive",
            callId="large-document",
            parentCallId="large-gateway",
            message=large_message,
        ),
        event(
            transaction,
            32,
            100,
            "cm-gateway",
            "response",
            serviceId="/documents/archive",
            callId="large-gateway",
            httpStatus="504 Gateway Timeout",
            response={"code": "DOCUMENT_TIMEOUT", "message": "archive timed out"},
        ),
    ]


def main() -> None:
    records = [
        *success_demo(),
        *business_error_demo(),
        *java_timeout_demo(),
        *retry_demo(),
        *multi_service_demo(),
        *large_log_demo(),
    ]
    OUTPUT.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    size_mb = OUTPUT.stat().st_size / 1_000_000
    print(f"generated {len(records)} records: {OUTPUT} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
