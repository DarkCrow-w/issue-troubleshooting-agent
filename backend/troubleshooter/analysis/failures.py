"""Deterministic facts: these remain available even if a model is unavailable."""

from troubleshooter.domain.models import Event

from .ordering import time_key


def failure_localization(events: list[Event], config: dict, artifacts: dict) -> dict:
    failures = []
    success_codes = set(config["success_business_codes"])
    for event in sorted(events, key=time_key):
        reasons = []
        if event.exception:
            reasons.append("异常：" + event.exception["type"])
        if event.http_status is not None and event.http_status >= 400:
            reasons.append(f"HTTP {event.http_status}")
        if event.business_code is not None and event.business_code not in success_codes:
            reasons.append(f"非成功业务码：{event.business_code}（按当前配置）")
        if event.level in ("ERROR", "FATAL"):
            reasons.append("错误级别日志")
        if reasons:
            failures.append(
                {
                    "event_id": event.id,
                    "service": event.service,
                    "api": event.api,
                    "timestamp": event.timestamp,
                    "reasons": reasons,
                }
            )
    return {
        "failures": failures,
        "earliest_observed_failure": failures[0] if failures else None,
        "caution": "最早观测到的失败不是根因证明；跨主机时钟可能存在偏差。",
    }
